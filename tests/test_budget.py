"""Offline CLI contract tests; the usage reader is a counting executable stub."""
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

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

    def test_missing_arguments(self):
        self.assertEqual(self.cli('available', '--engine', 'claude').returncode, 2)


if __name__ == '__main__':
    unittest.main()
