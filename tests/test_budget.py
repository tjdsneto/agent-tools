"""Offline CLI contract tests; the usage reader is a counting executable stub."""
import concurrent.futures
import json
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (ROOT / 'tests/fixtures/budget/fable.txt').read_text()


class BudgetTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'tmp').mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / 'tmp')
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.raw = self.path / 'usage'
        self.raw.write_text(FIXTURE)
        self.count = self.path / 'reads'
        stub = self.path / 'claude'
        stub.write_text('#!/bin/bash\n[ "$*" = "-p /usage" ] || exit 9\necho read >> "$READS"\ncat "$USAGE"\nexit "${READER_EXIT:-0}"\n')
        stub.chmod(0o755)
        self.env = dict(os.environ, CLAUDE_BIN=str(stub), READS=str(self.count),
                        USAGE=str(self.raw), BUDGET_CACHE_DIR=str(self.path / 'cache'))

        self.env['PYTHONPATH'] = str(ROOT / 'tests/fixtures/budget')
        self.env['BUDGET_FIXTURES'] = str(ROOT / 'tests/fixtures/budget')
        codex = self.path / 'codex'
        codex.write_text("""#!/usr/bin/env python3
import json, os, pathlib, sys, time
assert sys.argv[1:] == ['app-server', '--listen', 'stdio://']
pathlib.Path(os.environ['CODEX_PID']).write_text(str(os.getpid()))
for line in sys.stdin:
    request = json.loads(line)
    method = request['method']
    with open(os.environ['CODEX_CALLS'], 'a') as log:
        log.write(method + '\\n')
    if os.environ.get('CODEX_HANG'):
        time.sleep(60)
    if method == 'initialize':
        assert request['params']['clientInfo']['name'] == 'agt-budget'
        print(json.dumps({'id': 1, 'result': {}}), flush=True)
    elif method == 'account/rateLimits/read':
        if os.environ.get('CODEX_FAIL'):
            print(json.dumps({'id': 2, 'error': {'message': 'private body'}}), flush=True)
        else:
            value = json.loads((pathlib.Path(os.environ['BUDGET_FIXTURES']) / 'codex.json').read_text())
            print(json.dumps({'method': 'notification'}), flush=True)
            print(json.dumps({'id': 2, 'result': value}), flush=True)
        time.sleep(60)
""")
        codex.chmod(0o755)
        self.env.update(CODEX_BIN=str(codex), CODEX_PID=str(self.path / 'codex-pid'),
                        CODEX_CALLS=str(self.path / 'codex-calls'),
                        CURSOR_CALLS=str(self.path / 'cursor-calls'))

    def cli(self, *args):
        return subprocess.run([str(ROOT / 'agt/agt'), 'budget', *args],
                              env=self.env, text=True, capture_output=True)

    def available(self, model='fable', engine='claude'):
        result = self.cli('available', '--engine', engine, '--model', model)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def test_matching_family_and_versioned_model(self):
        self.assertEqual(self.available(), 'available')
        self.assertEqual(self.available('claude-fable-4-5'), 'available')

    def test_other_family_is_unknown(self):
        self.assertEqual(self.available('opus'), 'unknown')

    def test_codex_without_reading_usage(self):
        self.assertEqual(self.available('gpt-6-astra', 'codex'), 'unknown')
        self.assertFalse(self.count.exists())

    def test_session_exhaustion(self):
        self.raw.write_text(FIXTURE.replace('12%', '88%'))
        self.assertEqual(self.available(), 'unavailable')

    def test_week_exhaustion(self):
        self.raw.write_text(FIXTURE.replace('24%', '100%'))
        self.assertEqual(self.available(), 'unavailable')
        self.assertEqual(self.available('opus'), 'unknown')

    def test_missing_or_invalid_windows(self):
        for raw in ('', 'Current session: 12%', FIXTURE.replace('12%', '101%')):
            with self.subTest(raw=raw):
                self.raw.write_text(raw)
                self.env['BUDGET_CACHE_DIR'] = str(self.path / ('cache' + str(len(raw))))
                self.assertEqual(self.available(), 'unknown')

    def test_failed_reader_is_unknown(self):
        self.env['READER_EXIT'] = '1'
        self.assertEqual(self.available(), 'unknown')

    def test_shared_cache_across_concurrent_and_sequential_calls(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(list(pool.map(lambda _: self.available(), range(4))), ['available'] * 4)
        self.assertEqual(self.available('opus'), 'unknown')
        self.assertEqual(self.count.read_text().splitlines(), ['read'])

    def test_expired_cache_reads_again(self):
        self.assertEqual(self.available(), 'available')
        cache = self.path / 'cache/usage.json'
        value = json.loads(cache.read_text())
        value['read_at'] -= 61
        cache.write_text(json.dumps(value))
        self.raw.write_text(FIXTURE.replace('24%', '100%'))
        self.assertEqual(self.available(), 'unavailable')
        self.assertEqual(len(self.count.read_text().splitlines()), 2)

    def test_snapshot_contract(self):
        result = self.cli('snapshot')
        fields = dict(line.split('=', 1) for line in result.stdout.splitlines())
        self.assertEqual(fields['session_pct'], '12')
        self.assertEqual(fields['week_pct'], '24')
        self.assertEqual(fields['week_family'], 'Fable')
        reset = subprocess.check_output(['date', '-r', fields['week_reset'], '+%m-%d %H:%M'], text=True).strip()
        self.assertEqual(reset, '11-29 06:00')
        self.assertFalse((self.path / 'codex-calls').exists())
        self.assertFalse((self.path / 'cursor-calls').exists())

    def usage(self):
        result = self.cli('usage')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertNotIn('fixture-only-token', result.stdout)
        self.assertNotIn('private body', result.stdout)
        return json.loads(result.stdout)

    def test_usage_contract_and_server_cleanup(self):
        value = self.usage()
        self.assertEqual(set(value), {'claude', 'cursor', 'codex'})
        self.assertEqual(value['claude']['session_pct'], 12)
        self.assertEqual(value['claude']['week_pct'], 24)
        self.assertEqual(value['claude']['week_family'], 'Fable')
        self.assertIsInstance(value['claude']['session_reset'], int)
        self.assertIsInstance(value['claude']['week_reset'], int)
        self.assertEqual(value['cursor'], {
            'cycle_start': 1793491200, 'cycle_end': 1796083200,
            'included_pct': 64.0, 'total_pct': 3.7, 'auto_pct': 3.9,
            'api_pct': 2.6, 'message': "You've used 64% of your included usage"})
        self.assertEqual(value['codex'], {'primary_pct': 12, 'primary_window_mins': 300,
                         'primary_reset': 1795798800, 'weekly_pct': 34,
                         'weekly_window_mins': 10080, 'weekly_reset': 1796256000})
        self.assertEqual(self.count.read_text().splitlines(), ['read'])
        self.assertEqual((self.path / 'codex-calls').read_text().splitlines(),
                         ['initialize', 'initialized', 'account/rateLimits/read'])
        with self.assertRaises(ProcessLookupError):
            os.kill(int((self.path / 'codex-pid').read_text()), 0)

    def test_usage_failure_isolation(self):
        for flag, engine, error in [('READER_EXIT', 'claude', 'unread'),
                                    ('CURSOR_FAIL', 'cursor', 'unread'),
                                    ('NO_LOGIN', 'cursor', 'no login'),
                                    ('HTTP_ERROR', 'cursor', 'http 401'),
                                    ('CODEX_FAIL', 'codex', 'unread')]:
            with self.subTest(flag=flag):
                self.env[flag] = '1'
                value = self.usage()
                del self.env[flag]
                self.assertEqual(value[engine], {'error': error})
                for other in set(value) - {engine}:
                    self.assertNotIn('error', value[other])

    def usage_module(self):
        spec = importlib.util.spec_from_file_location('budget_usage', ROOT / 'modules/waker/budget-usage.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_codex_timeout_reaps_server(self):
        module = self.usage_module()
        self.env['CODEX_HANG'] = '1'
        with patch.dict(os.environ, self.env):
            self.assertEqual(module.bounded_read('codex', timeout=10), {'error': 'unread'})
        pid = int((self.path / 'codex-pid').read_text())
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_optional_sentence_and_invalid_windows(self):
        module = self.usage_module()
        data = json.loads((ROOT / 'tests/fixtures/budget/cursor.json').read_text())
        data['displayMessage'] = 'No percentage in this sentence'
        self.assertNotIn('included_pct', module.cursor_windows(data))
        data['displayMessage'] = 'You have used 12.5% of your included usage'
        self.assertEqual(module.cursor_windows(data)['included_pct'], 12.5)
        data['planUsage']['totalPercentUsed'] = None
        with self.assertRaises(ValueError):
            module.cursor_windows(data)
        with self.assertRaises((KeyError, TypeError)):
            module.codex_windows({'rateLimits': {'primary': None}})

    def test_usage_help(self):
        result = self.cli()
        self.assertEqual(result.returncode, 2)
        self.assertIn('usage |', result.stderr)

    def test_missing_arguments(self):
        self.assertEqual(self.cli('available', '--engine', 'claude').returncode, 2)


if __name__ == '__main__':
    unittest.main()
