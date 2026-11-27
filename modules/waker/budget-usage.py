"""Combined account windows; each reader runs in a bounded, isolated process."""
import concurrent.futures
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import urllib.error
import urllib.request

TIMEOUT = 30
UNREAD = {'error': 'unread'}


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('invalid number')
    return value


def cursor_windows(data):
    plan = data['planUsage']
    message = data.get('displayMessage', '')
    if not isinstance(message, str):
        raise ValueError('invalid message')
    result = {
        'cycle_start': int(data['billingCycleStart']) // 1000,
        'cycle_end': int(data['billingCycleEnd']) // 1000,
        'total_pct': round(number(plan['totalPercentUsed']), 1),
        'auto_pct': round(number(plan['autoPercentUsed']), 1),
        'api_pct': round(number(plan['apiPercentUsed']), 1),
        'message': message,
    }
    match = re.search(r'\bused\s+(\d+(?:\.\d+)?)%', message, re.I)
    if match:
        result['included_pct'] = float(match[1])
    return result


def codex_windows(data):
    result = {}
    for source, target in [('primary', 'primary'), ('secondary', 'weekly')]:
        window = data['rateLimits'][source]
        for field, key in [('usedPercent', 'pct'), ('windowDurationMins', 'window_mins'), ('resetsAt', 'reset')]:
            result[f'{target}_{key}'] = number(window[field])
    return result


def read_claude():
    result = subprocess.run([str(Path(__file__).with_name('claude-budget')), '_usage-snapshot'],
                            capture_output=True, text=True, check=True)
    fields = dict(line.split('=', 1) for line in result.stdout.splitlines())
    return {key: fields[key] if key == 'week_family' else int(fields[key])
            for key in ['session_pct', 'session_reset', 'week_pct', 'week_reset', 'week_family']}


def read_cursor():
    login = subprocess.run(['security', 'find-generic-password', '-a', 'cursor-user',
                            '-s', 'cursor-access-token', '-w'], capture_output=True, text=True)
    if login.returncode or not login.stdout.strip():
        return {'error': 'no login'}
    request = urllib.request.Request(
        'https://api2.cursor.sh/aiserver.v1.DashboardService/GetCurrentPeriodUsage',
        data=b'{}', headers={'Authorization': 'Bearer ' + login.stdout.strip(),
                            'Content-Type': 'application/json', 'Connect-Protocol-Version': '1'})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return cursor_windows(json.load(response))
    except urllib.error.HTTPError as error:
        return {'error': f'http {error.code}'}


def read_codex():
    process = subprocess.Popen([os.environ.get('CODEX_BIN', 'codex'), 'app-server', '--listen', 'stdio://'],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, text=True)
    def send(value):
        process.stdin.write(json.dumps(value) + '\n')
        process.stdin.flush()

    def reply(request_id):
        for line in process.stdout:
            value = json.loads(line)
            if value.get('id') == request_id:
                return value['result']
        raise ValueError('missing reply')

    try:
        send({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
              'params': {'clientInfo': {'name': 'agt-budget', 'version': '1'}}})
        reply(1)
        send({'jsonrpc': '2.0', 'method': 'initialized'})
        send({'jsonrpc': '2.0', 'id': 2, 'method': 'account/rateLimits/read'})
        return codex_windows(reply(2))
    finally:
        process.kill()
        process.wait()
        process.stdin.close()
        process.stdout.close()


def bounded_read(engine, timeout=TIMEOUT):
    process = subprocess.Popen([sys.executable, __file__, engine], stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, text=True, start_new_session=True)
    try:
        output, _ = process.communicate(timeout=timeout)
        return json.loads(output) if process.returncode == 0 else UNREAD.copy()
    except subprocess.TimeoutExpired:
        # Let the worker reap its server before killing any remaining descendants.
        process.terminate()
        try:
            process.communicate(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        return UNREAD.copy()
    except ValueError:
        return UNREAD.copy()
    finally:
        # Also stop descendants (Claude snapshot or Codex server) after a timeout.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()


def main():
    if len(sys.argv) > 1:
        def timed_out(signum, frame):
            raise TimeoutError()
        signal.signal(signal.SIGTERM, timed_out)
        try:
            value = {'claude': read_claude, 'cursor': read_cursor, 'codex': read_codex}[sys.argv[1]]()
        except Exception:
            # Never serialize exception text: upstream errors may carry credentials or bodies.
            value = UNREAD.copy()
    else:
        engines = ['claude', 'cursor', 'codex']
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            value = dict(zip(engines, pool.map(bounded_read, engines)))
    print(json.dumps(value, allow_nan=False))


if __name__ == '__main__':
    main()
