"""Share one Claude usage read for 60 seconds across availability processes."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def read_usage(reader):
    directory = Path(os.environ.get('BUDGET_CACHE_DIR',
                     str(Path.home() / '.cache/agent-tools/budget')))
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    cache = directory / 'usage.json'
    with (directory / 'usage.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            saved = json.loads(cache.read_text())
            age = time.time() - saved['read_at']
            if saved['reader'] == reader and 0 <= age < 60:
                return saved['raw']
        except (OSError, ValueError, KeyError, TypeError):
            pass
        try:
            result = subprocess.run([reader, '-p', '/usage'], capture_output=True,
                                    text=True, timeout=30)
            raw = result.stdout if result.returncode == 0 else ''
        except (OSError, subprocess.TimeoutExpired):
            raw = ''
        cache.write_text(json.dumps({'read_at': time.time(), 'reader': reader, 'raw': raw}))
        return raw


if __name__ == '__main__':
    try:
        print(read_usage(sys.argv[1]), end='')
    except OSError:
        # A cache that cannot be used must not trigger an uncoordinated paid read.
        sys.exit(1)
