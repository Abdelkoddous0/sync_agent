"""Offline acceptance: injected stores, real files, event-driven workers."""
import hashlib
import json
from pathlib import Path
import sys
import threading

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sync_engine import SyncEngine


class OfflineStore:
    def __init__(self, files=None):
        self.files = dict(files or {})
        self.uploads = []
        self.on_download = None
        self.on_upload = None

    def list(self):
        return {name: hashlib.sha256(data).hexdigest() for name, data in self.files.items()}

    def download(self, name, target, expected, stop):
        assert self.list()[name] == expected
        target.write(self.files[name])
        if self.on_download:
            self.on_download()

    def upload(self, name, source, expected):
        assert self.list().get(name) == expected
        if self.on_upload:
            self.on_upload()
        data = source.read()
        self.uploads.append(data)
        self.files[name] = data
        return self.list()[name]

    def delete(self, name, expected):
        assert self.list()[name] == expected
        del self.files[name]


def make_engine(tmp_path, store, **options):
    root = tmp_path / 'local'
    root.mkdir(exist_ok=True)
    return SyncEngine({'local_path': str(root), 's3_bucket': 'bucket',
                       's3_prefix': 'prefix', 'debounce_secs': 3600,
                       'poll_interval': 3600, **options},
                      store=store, state_path=tmp_path / 'baseline.json')


def identity_path(data, fields):
    return data / ('baseline-' + hashlib.sha256(json.dumps(fields).encode()).hexdigest() + '.json')


@pytest.mark.parametrize('mode', ['profile', 'sso', 'roles_anywhere', 'workload_role'])
def test_auth_modes_have_distinct_identity_and_accept_null_profile(tmp_path, monkeypatch, mode):
    data = tmp_path / 'state'
    monkeypatch.setattr('config.DATA_DIR', data)
    profile = None if mode == 'workload_role' else 'account-a'
    cfg = {'local_path': str(tmp_path / 'local'), 's3_bucket': 'bucket',
           's3_prefix': 'prefix', 'aws_profile': profile, 'auth_method': mode}
    engine = SyncEngine(cfg, store=OfflineStore())
    fields = [str(engine.root), 'bucket', 'prefix', profile]
    assert engine.state_path == identity_path(data, fields + [mode])
    assert engine.state_path != SyncEngine({**cfg, 'auth_method': 'access_keys'}, store=OfflineStore()).state_path
    assert engine.state_path != SyncEngine({**cfg, 'aws_profile': 'account-b'}, store=OfflineStore()).state_path


@pytest.mark.parametrize('mode', [None, 'access_keys'])
def test_legacy_access_keys_keep_four_field_identity(tmp_path, monkeypatch, mode):
    monkeypatch.setattr('config.DATA_DIR', tmp_path / 'state')
    cfg = {'local_path': str(tmp_path / 'local'), 's3_bucket': 'bucket'}
    if mode is not None:
        cfg['auth_method'] = mode
    engine = SyncEngine(cfg, store=OfflineStore())
    assert engine.state_path == identity_path(tmp_path / 'state', [str(engine.root), 'bucket', '', 'sync-agent'])


@pytest.mark.parametrize('mode', ['profile', 'sso', 'roles_anywhere', 'workload_role'])
def test_auth_identity_change_refuses_existing_four_field_tombstones(tmp_path, monkeypatch, mode):
    data = tmp_path / 'state'
    data.mkdir()
    monkeypatch.setattr('config.DATA_DIR', data)
    profile = None if mode == 'workload_role' else 'account-a'
    cfg = {'local_path': str(tmp_path / 'local'), 's3_bucket': 'bucket',
           'aws_profile': profile, 'auth_method': mode}
    old = identity_path(data, [str(Path(cfg['local_path']).absolute()), 'bucket', '', profile])
    content = json.dumps({'version': 1, 'files': {'a': {'local': None, 'remote': 'retained'}}})
    old.write_text(content)
    with pytest.raises(ValueError, match='migration review'):
        SyncEngine(cfg, store=OfflineStore())
    assert old.read_text() == content
    assert list(data.iterdir()) == [old]


@pytest.mark.parametrize('mode', ['access_keys', 'profile', 'sso', 'roles_anywhere', 'workload_role'])
def test_three_field_legacy_baseline_still_requires_review(tmp_path, monkeypatch, mode):
    data = tmp_path / 'state'
    data.mkdir()
    monkeypatch.setattr('config.DATA_DIR', data)
    root = str((tmp_path / 'local').absolute())
    old = identity_path(data, [root, 'bucket', ''])
    content = json.dumps({'version': 1, 'files': {'a': {'local': 'retained', 'remote': None}}})
    old.write_text(content)
    with pytest.raises(ValueError, match='Legacy baseline.*migration review'):
        SyncEngine({'local_path': root, 's3_bucket': 'bucket', 'auth_method': mode,
                    'aws_profile': None if mode == 'workload_role' else 'account-a'}, store=OfflineStore())
    assert old.read_text() == content
    assert list(data.iterdir()) == [old]


def test_existing_auth_specific_baseline_is_loaded_even_when_prior_exists(tmp_path, monkeypatch):
    data = tmp_path / 'state'
    data.mkdir()
    monkeypatch.setattr('config.DATA_DIR', data)
    fields = [str((tmp_path / 'local').absolute()), 'bucket', '', 'account-a']
    identity_path(data, fields).write_text(json.dumps({'version': 1, 'files': {}}))
    tombstones = {'a': {'local': None, 'remote': 'retained'}}
    current = identity_path(data, fields + ['sso'])
    current.write_text(json.dumps({'version': 1, 'files': tombstones}))
    engine = SyncEngine({'local_path': fields[0], 's3_bucket': 'bucket',
                         'aws_profile': 'account-a', 'auth_method': 'sso'}, store=OfflineStore())
    assert engine.state_path == current
    assert engine.baseline == tombstones


def test_first_sync_conflict_preserves_both_files_and_no_baseline(tmp_path):
    store = OfflineStore({'a': b'remote original'})
    engine = make_engine(tmp_path, store)
    (engine.root / 'a').write_bytes(b'local original')
    for _ in range(2):
        report = engine.sync()
        assert report['conflicts'] == ['a: untracked on both sides']
        assert not report['errors']
        assert engine.baseline == {}
        assert (engine.root / 'a').read_bytes() == b'local original'
        assert store.files == {'a': b'remote original'}
    assert store.uploads == []


def test_edit_while_downloading_preserves_edit_and_durable_baseline(tmp_path):
    store = OfflineStore({'a': b'original'})
    engine = make_engine(tmp_path, store)
    assert not engine.sync()['errors']
    baseline = json.loads(engine.state_path.read_text())
    store.files['a'] = b'remote edit'
    store.on_download = lambda: (engine.root / 'a').write_bytes(b'user edit')
    assert engine.sync()['errors']
    assert (engine.root / 'a').read_bytes() == b'user edit'
    assert json.loads(engine.state_path.read_text()) == baseline
    assert not list(engine.root.glob('.sync-agent-*'))
    restarted = make_engine(tmp_path, store)
    assert restarted.sync()['conflicts']
    assert store.files['a'] == b'remote edit'


def test_edit_during_upload_uses_snapshot_then_retries_new_bytes(tmp_path):
    store = OfflineStore()
    engine = make_engine(tmp_path, store)
    target = engine.root / 'a'
    target.write_bytes(b'snapshot')
    store.on_upload = lambda: target.write_bytes(b'new user edit')
    assert not engine.sync()['errors']
    assert target.read_bytes() == b'new user edit'
    assert store.files['a'] == b'snapshot'
    assert engine.baseline['a']['local'] == hashlib.sha256(b'snapshot').hexdigest()
    store.on_upload = None
    restarted = make_engine(tmp_path, store)
    assert not restarted.sync()['errors']
    assert store.uploads == [b'snapshot', b'new user edit']
    assert store.files['a'] == target.read_bytes() == b'new user edit'
    assert restarted.sync()['changed'] == []


@pytest.mark.parametrize('deleted_side', ['local', 'remote'])
@pytest.mark.parametrize('propagate', [False, True])
def test_deletion_tombstones_survive_restart_without_resurrection(tmp_path, deleted_side, propagate):
    store = OfflineStore({'a': b'original'})
    options = {'delete_on_s3': propagate, 'delete_local': propagate}
    engine = make_engine(tmp_path, store, **options)
    assert not engine.sync()['errors']
    if deleted_side == 'local':
        (engine.root / 'a').unlink()
    else:
        del store.files['a']
    assert not engine.sync()['errors']
    expected_local = (engine.root / 'a').exists()
    expected_remote = 'a' in store.files
    assert not (expected_local if deleted_side == 'local' else expected_remote)
    for _ in range(2):
        engine = make_engine(tmp_path, store, **options)
        assert not engine.sync()['errors']
        assert (engine.root / 'a').exists() == expected_local
        assert ('a' in store.files) == expected_remote
    if not propagate:
        if deleted_side == 'local':
            store.files['a'] = b'new remote edit'
        else:
            (engine.root / 'a').write_bytes(b'new local edit')
        assert engine.sync()['conflicts']
        assert (engine.root / 'a').exists() == expected_local
        assert ('a' in store.files) == expected_remote


class GatedStore(OfflineStore):
    def __init__(self):
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()
        self.followup = threading.Event()
        self.calls = 0
        self.active = 0
        self.max_active = 0
        self.guard = threading.Lock()

    def list(self):
        with self.guard:
            self.calls += 1
            call = self.calls
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            if call == 1:
                self.entered.set()
                assert self.release.wait(3), 'test did not release the first pass'
            else:
                self.followup.set()
            return {}
        finally:
            with self.guard:
                self.active -= 1


def test_manual_request_bypasses_debounce_and_cannot_be_postponed_by_event(tmp_path):
    store = GatedStore()
    engine = make_engine(tmp_path, store)
    engine.start()
    try:
        assert store.entered.wait(2)
        assert engine.request_sync('watcher')
        assert engine.request_sync('manual', immediate=True)
        # A watcher burst arriving before the worker resumes cannot undo manual intent.
        assert engine.request_sync('watcher')
        store.release.set()
        assert store.followup.wait(2), 'manual request lost to trailing debounce'
    finally:
        store.release.set()
        assert engine.stop(3)
    assert store.calls == 2
    assert store.max_active == 1


def test_pending_request_during_running_pass_is_not_lost(tmp_path):
    store = GatedStore()
    engine = make_engine(tmp_path, store)
    engine.start()
    try:
        assert store.entered.wait(2)
        for _ in range(10):
            assert engine.request_sync('manual', immediate=True)
        store.release.set()
        assert store.followup.wait(2)
    finally:
        store.release.set()
        assert engine.stop(3)
    assert store.calls == 2
    assert store.max_active == 1
    assert not engine.request_sync('after stop', immediate=True)
    assert not engine._worker.is_alive()


def test_stop_waits_for_active_pass_and_drops_pending_work(tmp_path):
    store = GatedStore()
    engine = make_engine(tmp_path, store)
    engine.start()
    try:
        assert store.entered.wait(2)
        assert engine.request_sync('manual', immediate=True)
        assert engine.stop(timeout=0) is False
        assert not engine.request_sync('stopped', immediate=True)
    finally:
        store.release.set()
        assert engine.stop(3)
    assert store.calls == 1
    assert not engine._worker.is_alive()


def test_direct_and_worker_sync_do_not_overlap(tmp_path):
    store = GatedStore()
    engine = make_engine(tmp_path, store)
    caller_started = threading.Event()
    caller_done = threading.Event()
    reports = []

    def direct_sync():
        caller_started.set()
        reports.append(engine.sync())
        caller_done.set()

    caller = threading.Thread(target=direct_sync)
    engine.start()
    try:
        assert store.entered.wait(2)
        caller.start()
        assert caller_started.wait(2)
        assert not caller_done.is_set()
        store.release.set()
        assert caller_done.wait(2)
    finally:
        store.release.set()
        if caller.ident is not None:
            caller.join(3)
        assert engine.stop(3)
    assert not caller.is_alive()
    assert store.calls == 2
    assert store.max_active == 1
    assert reports == [{'changed': [], 'conflicts': [], 'errors': []}]


def test_stop_during_download_preserves_destination_and_baseline(tmp_path):
    store = OfflineStore({'a': b'original'})
    engine = make_engine(tmp_path, store)
    assert not engine.sync()['errors']
    baseline = engine.state_path.read_bytes()
    store.files['a'] = b'remote edit'
    entered = threading.Event()
    release = threading.Event()

    def block_download():
        entered.set()
        assert release.wait(3)

    store.on_download = block_download
    engine.start()
    try:
        assert entered.wait(2)
        assert engine.stop(0) is False
    finally:
        release.set()
        assert engine.stop(3)
    assert (engine.root / 'a').read_bytes() == b'original'
    assert engine.state_path.read_bytes() == baseline
    assert not list(engine.root.glob('.sync-agent-*'))
    assert engine.last_report['errors'] == ['a: InterruptedError']


@pytest.mark.parametrize('failure_point', ['list', 'download', 'upload'])
def test_store_exception_secrets_are_not_in_reports_or_logs(tmp_path, caplog, failure_point):
    store = OfflineStore({'a': b'remote'} if failure_point == 'download' else {})
    engine = make_engine(tmp_path, store)
    if failure_point == 'upload':
        (engine.root / 'a').write_bytes(b'local')
    secret = 'SECRET_SESSION_TOKEN_do_not_log'

    def fail(*args):
        raise RuntimeError('credential_process failed: ' + secret)

    setattr(store, failure_point, fail)
    report = engine.sync()
    assert report['errors']
    assert secret not in json.dumps(report)
    assert secret not in caplog.text
    assert 'RuntimeError' in json.dumps(report)
