"""Bounded subprocess logging shared by remote probes."""
import os
from pathlib import Path
import subprocess


def run_logged(command, path, *, cwd, env, timeout):
    """Stream diagnostics while retaining a subprocess/process-group deadline."""
    import signal
    import threading
    if timeout <= 0:
        raise TimeoutError('No subprocess budget remains')
    with Path(path).open('w') as log:
        child = subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, errors='replace', start_new_session=True)

        def relay():
            for line in child.stdout:
                log.write(line)
                log.flush()
                print(line, end='', flush=True)

        reader = threading.Thread(target=relay, daemon=True)
        reader.start()
        try:
            return child.wait(timeout=timeout)
        finally:
            # Also clean up descendants if the leader exited before its children.
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()
            reader.join(timeout=5)
