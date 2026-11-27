"""Child-process fixture harness: replace account I/O before the reader imports."""
import io
import json
import os
from pathlib import Path
import subprocess
import urllib.error
import urllib.request

if os.environ.get('BUDGET_FIXTURES'):
    fixtures = Path(os.environ['BUDGET_FIXTURES'])
    original_run = subprocess.run

    def run(args, *positional, **kwargs):
        if args[0] == 'security':
            Path(os.environ['CURSOR_CALLS']).write_text('read')
            assert args == ['security', 'find-generic-password', '-a', 'cursor-user', '-s', 'cursor-access-token', '-w']
            return subprocess.CompletedProcess(args, 1 if os.environ.get('NO_LOGIN') else 0, 'fixture-only-token\n', '')
        return original_run(args, *positional, **kwargs)

    def urlopen(request, timeout):
        assert request.full_url == 'https://api2.cursor.sh/aiserver.v1.DashboardService/GetCurrentPeriodUsage'
        assert request.data == b'{}'
        assert request.get_header('Authorization') == 'Bearer fixture-only-token'
        assert request.get_header('Connect-protocol-version') == '1'
        assert request.get_header('Content-type') == 'application/json'
        if os.environ.get('HTTP_ERROR'):
            raise urllib.error.HTTPError(request.full_url, 401, 'fixture-only-token private body', {}, None)
        if os.environ.get('CURSOR_FAIL'):
            raise ValueError('fixture-only-token private body')
        return io.BytesIO((fixtures / 'cursor.json').read_bytes())

    subprocess.run = run
    urllib.request.urlopen = urlopen
