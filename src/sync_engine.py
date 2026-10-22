"""Serialized per-file reconciliation. No CLI mirrors or implicit deletes.

SyncEngine(cfg, store=None, state_path=None): inject a store for offline use.
sync() -> {conflicts: list, errors: list, changed: list} runs synchronously,
serialized against all other passes. request_sync(reason='event', immediate=False)
queues a trailing-debounced pass, retaining requests made during a running pass.
start() starts one worker; stop(timeout=30)->bool waits for it. Conflicts keep
both originals untouched and are retried/reported until explicitly resolved.
Store interface: list()->{relative_name: opaque_version}, download(name, binary
file, expected_version, stop_event), upload(name, binary_file, expected_version)
->new_version, delete(name, expected_version). None means expected absence.
"""
import fnmatch
import hashlib
import json
import logging
import os
from pathlib import Path
import stat
import tempfile
import threading
import time
import unicodedata

from aws_errors import describe as describe_error

REPEAT_LOG_SECONDS = 600


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.state-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def safe_name(name):
    if not isinstance(name, str) or not name or '\\' in name:
        return False
    for part in name.split('/'):
        if (part in ('', '.', '..') or part[-1:] in (' ', '.')
                or any(ord(c) < 32 or c in '<>:"|?*' for c in part)
                or part.split('.')[0].upper() in {'CON','PRN','AUX','NUL','CONIN$','CONOUT$',
                    *(f'COM{i}' for i in '123456789¹²³'), *(f'LPT{i}' for i in '123456789¹²³')}):
            return False
    return True


def linked(path):
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


class SyncEngine:
    def __init__(self, cfg, store=None, state_path=None):
        self.cfg = dict(cfg)
        self.root = Path(cfg['local_path']).absolute()
        if store is None:
            from storage import S3Store
            store = S3Store(cfg)
        self.store = store
        if state_path is None:
            from config import DATA_DIR
            fields = [str(self.root), cfg['s3_bucket'], cfg.get('s3_prefix',''), cfg.get('aws_profile','sync-agent')]
            prior_identity = json.dumps(fields)
            auth_method = cfg.get('auth_method', 'access_keys')
            if auth_method != 'access_keys':
                fields.append(auth_method)
            identity = json.dumps(fields)
            state_path = DATA_DIR / ('baseline-' + hashlib.sha256(identity.encode()).hexdigest() + '.json')
            prior = DATA_DIR / ('baseline-' + hashlib.sha256(prior_identity.encode()).hexdigest() + '.json')
            if not state_path.exists() and prior != state_path and prior.exists():
                raise ValueError('Authentication baseline requires explicit migration review; refusing a fresh baseline')
            legacy_identity = json.dumps([str(self.root), cfg['s3_bucket'], cfg.get('s3_prefix','')])
            legacy = DATA_DIR / ('baseline-' + hashlib.sha256(legacy_identity.encode()).hexdigest() + '.json')
            if not state_path.exists() and legacy.exists():
                raise ValueError('Legacy baseline requires explicit profile/migration review; refusing a fresh baseline')
        self.state_path = Path(state_path)
        self.baseline = {}
        if self.state_path.exists():
            state = json.loads(self.state_path.read_text(encoding='utf-8'))
            if state.get('version') != 1 or not isinstance(state.get('files'), dict):
                raise ValueError('Invalid baseline; refusing unsafe first-sync fallback')
            self.baseline = state['files']
        self._lock = threading.Lock()
        self._condition = threading.Condition()
        self._stop = threading.Event()
        self._due = None
        self._immediate_pending = False
        self._worker = None
        self._hashes = {}
        self.last_report = {'conflicts':[], 'errors':[], 'changed':[]}
        self._logged_issues = ()
        self._connected = False
        self._logged_at = 0.0

    def _log_issues(self, issues):
        # A persistent failure (bad clock, revoked key) repeats every poll: log it once, then a reminder.
        issues = tuple(issues)
        now = time.monotonic()
        if issues and issues == self._logged_issues and now - self._logged_at < REPEAT_LOG_SECONDS:
            return
        if not issues and self._logged_issues:
            logging.info('Previous sync problems resolved')
        repeat = issues == self._logged_issues
        for issue in issues:
            logging.warning('%s%s', 'Still failing: ' if repeat else '', issue)
        self._logged_issues, self._logged_at = issues, now

    def _path(self, name, create=False):
        if not safe_name(name):
            raise ValueError('Unsafe Windows path: ' + name)
        # Never resolve away a junction/symlink before checking it.
        chain = [self.root, *self.root.parents]
        for path in reversed(chain):
            if path.exists() and linked(path):
                raise ValueError('Symlink/reparse root')
        path = self.root
        for part in name.split('/'):
            if path.exists() and not path.is_dir():
                raise ValueError('Non-directory ancestor')
            if create:
                path.mkdir(exist_ok=True)
            path = path / part
            if path.is_symlink() or (path.exists() and linked(path)):
                raise ValueError('Symlink/reparse path')
        return path

    def _fingerprint(self, name):
        path = self._path(name)
        try:
            if not path.is_file():
                if path.exists():
                    raise ValueError('Destination is not a file')
                return None
            before = path.stat()
            h = hashlib.sha256()
            with path.open('rb') as f:
                for block in iter(lambda: f.read(1024*1024), b''):
                    if self._stop.is_set():
                        raise InterruptedError('Stopping')
                    h.update(block)
            after = path.stat()
            if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
                raise ValueError('Local file changed while reading')
            return h.hexdigest()
        except FileNotFoundError:
            return None

    # Files modified this recently are always re-hashed: a second write within the
    # filesystem timestamp granularity can keep size and mtime unchanged.
    RACY_SECONDS = 3

    def _scan_fingerprint(self, name, seen):
        """Scan-time hash reusing the previous digest while size/mtime/file ID are unchanged.

        Transfer guards still call _fingerprint() and hash the full content.
        """
        try:
            info = self._path(name).stat()
        except FileNotFoundError:
            return None
        key = (info.st_size, info.st_mtime_ns, info.st_ino)
        seen.add(name)
        cached = self._hashes.get(name)
        if cached and cached[0] == key:
            return cached[1]
        digest = self._fingerprint(name)
        if digest is not None and time.time_ns() - info.st_mtime_ns > self.RACY_SECONDS * 10**9:
            self._hashes[name] = (key, digest)
        else:
            self._hashes.pop(name, None)
        return digest

    def _included(self, name):
        return ((self.cfg.get('recursive', True) or '/' not in name)
                and not any(fnmatch.fnmatchcase(name, p) or fnmatch.fnmatchcase(Path(name).name, p)
                            for p in self.cfg.get('exclude_patterns', []))
                and not Path(name).name.startswith('.sync-agent-'))

    def _locals(self):
        if not self.root.is_dir():
            raise ValueError('Local root missing; refusing to interpret as deletion')
        self._path('_probe_')
        result = {}
        seen = set()
        def fail_scan(error):
            raise error
        for base, dirs, files in os.walk(self.root, followlinks=False, onerror=fail_scan):
            for name in list(dirs):
                p = Path(base)/name
                if linked(p):
                    raise ValueError('Symlink/reparse directory: ' + str(p))
            if not self.cfg.get('recursive',True):
                dirs[:] = []
            for file in files:
                name = (Path(base)/file).relative_to(self.root).as_posix()
                if self._included(name):
                    result[name] = self._scan_fingerprint(name, seen)
        for name in set(self._hashes) - seen:
            del self._hashes[name]
        return result

    def _download(self, name, remote, local):
        target = self._path(name, create=True)
        fd, temp = tempfile.mkstemp(prefix='.sync-agent-', dir=target.parent)
        try:
            with os.fdopen(fd, 'wb') as f:
                self.store.download(name, f, remote, self._stop)
                f.flush()
                os.fsync(f.fileno())
            if self._stop.is_set():
                raise InterruptedError('Stopping')
            if self._fingerprint(name) != local:
                raise ValueError('Local change during download')
            self._path(name)
            os.replace(temp, target)
            return self._fingerprint(name)
        finally:
            Path(temp).unlink(missing_ok=True)

    def sync(self):
        with self._lock:
            report = {'conflicts':[], 'errors':[], 'changed':[]}
            try:
                local = self._locals()
                remote = {k:v for k,v in self.store.list().items() if self._included(k)}
                names = set(local) | set(remote) | set(self.baseline)
                # Reject case/Unicode aliases, including aliases of ancestor directories.
                aliases = {}
                blocked = set()
                for name in sorted(names):
                    if not safe_name(name):
                        blocked.add(name)
                        continue
                    parts = name.split('/')
                    for i in range(1, len(parts)+1):
                        component = '/'.join(parts[:i])
                        alias = unicodedata.normalize('NFC', component).casefold()
                        aliases.setdefault(alias, set()).add(component)
                collisions = {a for a, values in aliases.items() if len(values)>1}
                for name in names:
                    if any(unicodedata.normalize('NFC','/'.join(name.split('/')[:i])).casefold() in collisions
                           for i in range(1,len(name.split('/'))+1)):
                        blocked.add(name)
                for name in sorted(names):
                    if self._stop.is_set():
                        break
                    if name in blocked:
                        report['conflicts'].append(name + ': unsafe/colliding path')
                        continue
                    if not self._included(name):
                        continue
                    l, r = local.get(name), remote.get(name)
                    old = self.baseline.get(name)
                    try:
                        if old is None:
                            if l is not None and r is not None:
                                # No trusted baseline: never choose a winner by timestamp/ETag.
                                report['conflicts'].append(name + ': untracked on both sides')
                                continue
                            action = 'upload' if l is not None else 'download'
                        else:
                            lc, rc = l != old['local'], r != old['remote']
                            if not lc and not rc:
                                continue
                            if lc and rc:
                                if l is None and r is None:
                                    self.baseline[name] = {'local':None, 'remote':None}
                                    continue
                                report['conflicts'].append(name + ': both sides changed')
                                continue
                            action = 'upload' if lc else 'download'
                            if action == 'upload' and l is None:
                                if r is not None and self.cfg.get('delete_on_s3',False):
                                    self.store.delete(name, r)
                                    r = None
                                    logging.info('Deleted from S3 (deleted locally): %s', name)
                                self.baseline[name] = {'local':None, 'remote':r}
                                continue
                            if action == 'download' and not self.cfg.get('sync_from_s3',True):
                                continue
                            if action == 'download' and r is None:
                                if l is not None and self.cfg.get('delete_local',False):
                                    if self._fingerprint(name) != l:
                                        raise ValueError('Local change before deletion')
                                    self._path(name).unlink()
                                    l = None
                                    logging.info('Deleted locally (deleted on S3): %s', name)
                                self.baseline[name] = {'local':l, 'remote':None}
                                continue
                            # Retained deletion tombstone: never resurrect the absent side.
                            if (old['local'] is None or old['remote'] is None) and (l is None or r is None):
                                report['conflicts'].append(name + ': deletion retained; manual resolution required')
                                continue
                        if action == 'download':
                            if not self.cfg.get('sync_from_s3',True) or r is None:
                                continue
                            l = self._download(name, r, l)
                            logging.info('Downloaded %s', name)
                        elif l is not None:
                            if self._fingerprint(name) != l:
                                raise ValueError('Local change before upload')
                            # Snapshot first: SDK never streams a file being edited by its owner.
                            with tempfile.TemporaryFile() as snapshot:
                                with self._path(name).open('rb') as source:
                                    for block in iter(lambda:source.read(1024*1024),b''):
                                        snapshot.write(block)
                                snapshot.seek(0)
                                digest = hashlib.sha256()
                                for block in iter(lambda: snapshot.read(1024*1024), b''):
                                    digest.update(block)
                                if digest.hexdigest() != l:
                                    raise ValueError('Local change during snapshot')
                                snapshot.seek(0)
                                r = self.store.upload(name, snapshot, r)
                            logging.info('Uploaded %s', name)
                        self.baseline[name] = {'local':l, 'remote':r}
                        report['changed'].append(name)
                    except Exception as exc:
                        # Provider/credential-process messages can contain credentials: code only.
                        report['errors'].append(name + ': ' + describe_error(exc))
                atomic_json(self.state_path, {'version':1, 'files':self.baseline})
            except Exception as exc:
                report['errors'].append(describe_error(exc))
            self.last_report = report
            if not self._connected and not report['errors']:
                self._connected = True
                in_sync = sum(1 for entry in self.baseline.values() if entry['local'] is not None and entry['remote'] is not None)
                logging.info('Connected to S3: %d file(s) in sync', in_sync)
            self._log_issues(report['conflicts'] + report['errors'])
            return report

    def start(self):
        with self._condition:
            if self._worker is None:
                self._worker = threading.Thread(target=self._run, name='sync-worker', daemon=False)
                self._worker.start()
        self.request_sync('startup', immediate=True)

    def request_sync(self, reason='event', immediate=False):
        with self._condition:
            if self._stop.is_set():
                return False
            due = time.monotonic() + (0 if immediate else self.cfg.get('debounce_secs',5))
            if immediate:
                self._due = due if self._due is None else min(self._due, due)
                self._immediate_pending = True
            elif not self._immediate_pending:
                self._due = due
            self._condition.notify_all()
            return True

    def _run(self):
        next_poll = time.monotonic() + self.cfg.get('poll_interval',30)
        while not self._stop.is_set():
            with self._condition:
                now = time.monotonic()
                if now >= next_poll:
                    if self._due is None:
                        self._due = now
                    next_poll = now + self.cfg.get('poll_interval',30)
                if self._due is None or self._due > now:
                    wake = min(next_poll, self._due if self._due is not None else next_poll)
                    self._condition.wait(max(0,wake-now))
                    continue
                self._due = None
                self._immediate_pending = False
            self.sync()

    def stop(self, timeout=30):
        self._stop.set()
        with self._condition:
            self._condition.notify_all()
        if self._worker and self._worker is not threading.current_thread():
            self._worker.join(timeout)
        return not self._worker or not self._worker.is_alive()


# Lazy compatibility facade for the tray. Both old direction buttons request
# the SAME reconciliation worker; no second push/pull loop exists.
cfg = {}
engine = None
observer = None
tray_ref = None
sync_status = 'Idle'

def request_sync(reason='manual', immediate=True):
    return engine.request_sync(reason, immediate) if engine else False

sync_to_s3 = request_sync
sync_from_s3 = request_sync

def stop(timeout=30):
    return engine.stop(timeout) if engine else True

def stop_s3_poller():
    return stop()

def make_icon(color=(34,197,94)):
    from PIL import Image, ImageDraw
    image = Image.new('RGBA',(64,64),(0,0,0,0))
    ImageDraw.Draw(image).ellipse((3,3,61,61),fill=color)
    return image

def desktop_notify(title, message):
    if cfg.get('notifications',True):
        try:
            from plyer import notification
            notification.notify(title=title,message=message,app_name='Sync Agent',timeout=4)
        except Exception:
            logging.debug('Notification unavailable',exc_info=True)
