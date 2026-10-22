"""Per-user source/frozen-safe coordination without process-name/PID killing.

is_running()->bool probes an OS-held file lock, not stale PID metadata.
request_stop(timeout=30)->bool sends a random instance-token-scoped request,
returning True only when the lock is released. It never terminates processes.
RuntimeGuard.acquire()->bool owns the lock until close(); stop_event is set
by token-authenticated stop requests. Lock files are never unlinked (avoids
locking different inodes). Windows uses msvcrt byte locking; POSIX uses flock.
Optional data_dir parameters exist for isolated offline tests.
"""
import json
import os
from pathlib import Path
import secrets
import threading
import time
from sync_engine import atomic_json


def _directory(data_dir=None):
    if data_dir is None:
        from config import DATA_DIR
        data_dir = DATA_DIR
    return Path(data_dir)


def _lock(handle):
    handle.seek(0)
    try:
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except (OSError, BlockingIOError):
        return False


def _unlock(handle):
    handle.seek(0)
    if os.name == 'nt':
        import msvcrt
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _open_lock(directory):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory/'agent.lock'
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    if os.fstat(fd).st_size == 0:
        os.write(fd,b'0')
    return os.fdopen(fd,'r+b',buffering=0)


def is_running(data_dir=None):
    directory = _directory(data_dir)
    try:
        with _open_lock(directory) as handle:
            if not _lock(handle):
                return True
            _unlock(handle)
            return False
    except OSError:
        # Fail closed: maintenance must not replace files if state is unknown.
        return True


def request_stop(timeout=30, data_dir=None):
    directory = _directory(data_dir)
    deadline = time.monotonic() + max(0,timeout)
    while is_running(directory):
        try:
            info = json.loads((directory/'instance.json').read_text(encoding='utf-8'))
            token = info['token']
            if not isinstance(token,str) or len(token)!=64:
                return False
            atomic_json(directory/'stop.json', {'token':token})
        except (OSError,ValueError,KeyError):
            # Startup may hold lock before publishing its token.
            if time.monotonic() >= deadline:
                return False
            time.sleep(.05)
            continue
        while is_running(directory):
            if time.monotonic() >= deadline:
                return False
            try:
                current = json.loads((directory/'instance.json').read_text(encoding='utf-8'))
                if current.get('token') != token:
                    return False  # Replacement instance is NOT ours to stop.
            except (OSError,ValueError):
                pass
            time.sleep(.05)
        return True
    return True


class RuntimeGuard:
    def __init__(self, data_dir=None):
        self.directory = _directory(data_dir)
        self.stop_event = threading.Event()
        self._closing = threading.Event()
        self._handle = None
        self._thread = None
        self.token = secrets.token_hex(32)

    def acquire(self):
        if self._handle is not None:
            return True
        handle = _open_lock(self.directory)
        if not _lock(handle):
            handle.close()
            return False
        self._handle = handle
        try:
            atomic_json(self.directory/'instance.json', {'token':self.token, 'pid':os.getpid()})
            self._thread = threading.Thread(target=self._monitor,name='stop-monitor',daemon=True)
            self._thread.start()
            return True
        except Exception:
            self.close()
            raise

    def _monitor(self):
        while not self._closing.wait(.05):
            try:
                request = json.loads((self.directory/'stop.json').read_text(encoding='utf-8'))
                if request.get('token') == self.token:
                    self.stop_event.set()
            except (OSError,ValueError):
                pass

    def close(self):
        self._closing.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(2)
        if self._handle is not None:
            _unlock(self._handle)
            self._handle.close()
            self._handle = None
