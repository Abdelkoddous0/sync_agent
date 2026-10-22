import hashlib
from pathlib import Path
import sys
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

class FakeStore:
    def __init__(self, files=None):
        self.files = dict(files or {})
        self.writes = []
    def list(self):
        return {k: hashlib.sha256(v).hexdigest() for k,v in self.files.items()}
    def download(self, key, target, expected, stop):
        assert self.list()[key] == expected
        target.write(self.files[key])
    def upload(self, key, source, expected):
        assert self.list().get(key) == expected
        self.files[key] = source.read()
        self.writes.append(key)
        return self.list()[key]
    def delete(self, key, expected):
        assert self.list()[key] == expected
        del self.files[key]

def make_engine(tmp_path, store, **options):
    from sync_engine import SyncEngine
    root=tmp_path/'local'; root.mkdir(exist_ok=True)
    cfg={'local_path':str(root),'s3_bucket':'bucket','s3_prefix':'prefix',
         'debounce_secs':0.03,'poll_interval':100, **options}
    return SyncEngine(cfg, store=store, state_path=tmp_path/'baseline.json')

def test_directory_scan_failure_cannot_be_interpreted_as_deletion(tmp_path,monkeypatch):
    store=FakeStore({'nested/a':b'keep'})
    engine=make_engine(tmp_path,store,delete_on_s3=True)
    engine.sync()
    original=dict(engine.baseline)
    def denied_walk(root,followlinks=False,onerror=None):
        if onerror: onerror(PermissionError('injected unreadable directory'))
        return iter([])
    monkeypatch.setattr('sync_engine.os.walk',denied_walk)
    assert engine.sync()['errors']
    assert store.files=={'nested/a':b'keep'}
    assert engine.baseline==original


def test_snapshot_upload_supports_python_without_file_digest(tmp_path,monkeypatch):
    monkeypatch.delattr(hashlib,'file_digest',raising=False)
    store=FakeStore(); engine=make_engine(tmp_path,store)
    (engine.root/'a').write_bytes(b'local')
    assert not engine.sync()['errors']
    assert store.files['a']==b'local'


def test_baseline_identity_includes_aws_profile(tmp_path,monkeypatch):
    from sync_engine import SyncEngine
    monkeypatch.setattr('config.DATA_DIR',tmp_path/'state')
    cfg={'local_path':str(tmp_path/'files'),'s3_bucket':'example-bucket','s3_prefix':'ws22'}
    first=SyncEngine({**cfg,'aws_profile':'account-a'},store=FakeStore())
    second=SyncEngine({**cfg,'aws_profile':'account-b'},store=FakeStore())
    assert first.state_path!=second.state_path


def test_disabled_remote_sync_does_not_propagate_remote_deletion(tmp_path):
    store=FakeStore({'a':b'keep'})
    engine=make_engine(tmp_path,store,delete_local=True)
    engine.sync(); del store.files['a']
    engine.cfg['sync_from_s3']=False
    engine.sync()
    assert (engine.root/'a').read_bytes()==b'keep'
    assert engine.baseline['a']['remote'] is not None


def test_legacy_baseline_requires_review_instead_of_silent_first_sync(tmp_path,monkeypatch):
    import json
    import pytest
    from sync_engine import SyncEngine
    data=tmp_path/'state'; data.mkdir()
    monkeypatch.setattr('config.DATA_DIR',data)
    cfg={'local_path':str(tmp_path/'files'),'s3_bucket':'example-bucket','s3_prefix':'ws22'}
    identity=json.dumps([str(Path(cfg['local_path']).absolute()),cfg['s3_bucket'],cfg['s3_prefix']])
    old=data/('baseline-'+hashlib.sha256(identity.encode()).hexdigest()+'.json')
    old.write_text(json.dumps({'version':1,'files':{'a':{'local':'retained','remote':None}}}))
    with pytest.raises(ValueError,match='Legacy baseline'):
        SyncEngine(cfg,store=FakeStore())


def test_local_only_is_uploaded_not_deleted(tmp_path):
    store=FakeStore({'remote.txt':b'remote'})
    engine=make_engine(tmp_path,store)
    (engine.root/'local.txt').write_bytes(b'local')
    report=engine.sync()
    assert (engine.root/'local.txt').read_bytes()==b'local'
    assert (engine.root/'remote.txt').read_bytes()==b'remote'
    assert store.files['local.txt']==b'local'
    assert not report['conflicts']

def test_remote_deletion_is_not_resurrected_across_restart(tmp_path):
    store=FakeStore({'a':b'original'})
    engine=make_engine(tmp_path,store)
    engine.sync()
    del store.files['a']
    engine.sync()
    engine=make_engine(tmp_path,store)
    engine.sync()
    assert (engine.root/'a').read_bytes()==b'original'
    assert 'a' not in store.files
    (engine.root/'a').write_bytes(b'edited')
    assert engine.sync()['conflicts']
    assert 'a' not in store.files

def test_two_sided_changes_preserve_originals(tmp_path):
    store=FakeStore({'a':b'old'})
    engine=make_engine(tmp_path,store); engine.sync()
    (engine.root/'a').write_bytes(b'local')
    store.files['a']=b'remote'
    assert engine.sync()['conflicts']
    assert store.files['a']==b'remote'
    assert (engine.root/'a').read_bytes()==b'local'

def test_download_rechecks_local_change(tmp_path):
    store=FakeStore({'a':b'old'})
    engine=make_engine(tmp_path,store); engine.sync()
    store.files['a']=b'new'
    download=store.download
    def racing(key,target,expected,stop):
        download(key,target,expected,stop)
        (engine.root/'a').write_bytes(b'user edit')
    store.download=racing
    assert engine.sync()['errors']
    assert (engine.root/'a').read_bytes()==b'user edit'
    assert not list(engine.root.glob('.sync-agent-*'))

def test_download_failure_preserves_destination(tmp_path):
    store=FakeStore({'a':b'old'})
    engine=make_engine(tmp_path,store); engine.sync(); store.files['a']=b'new'
    def fail(key,target,expected,stop):
        target.write(b'partial'); raise OSError('offline')
    store.download=fail
    assert engine.sync()['errors']
    assert (engine.root/'a').read_bytes()==b'old'

def test_unsafe_windows_paths_and_case_aliases_are_blocked(tmp_path):
    store=FakeStore({k:b'evil' for k in ['../escape','/abs','C:/bad','CON.txt','d/NUL',
        'trailing.','ads:evil','back\\slash','dir/A','DIR/b','X','x']})
    engine=make_engine(tmp_path,store)
    assert engine.sync()['conflicts']
    assert not list(engine.root.iterdir())
    assert not (tmp_path/'escape').exists()

def test_symlink_is_never_followed(tmp_path):
    store=FakeStore({'a':b'remote'})
    engine=make_engine(tmp_path,store)
    outside=tmp_path/'outside'; outside.write_bytes(b'private')
    try:
        (engine.root/'a').symlink_to(outside)
    except OSError:
        pytest.skip('Symlink creation requires platform privileges')
    assert engine.sync()['errors']
    assert outside.read_bytes()==b'private'
    assert not store.writes

def test_local_delete_does_not_redownload_or_delete_remote(tmp_path):
    store=FakeStore({'a':b'old'})
    engine=make_engine(tmp_path,store); engine.sync()
    (engine.root/'a').unlink(); engine.sync(); engine.sync()
    assert not (engine.root/'a').exists()
    assert store.files['a']==b'old'

def test_explicit_deletion_only_after_baseline(tmp_path):
    store=FakeStore({'a':b'old'})
    engine=make_engine(tmp_path,store,delete_local=True,delete_on_s3=True); engine.sync()
    (engine.root/'localonly').write_bytes(b'keep')
    del store.files['a']; engine.sync()
    assert not (engine.root/'a').exists()
    assert (engine.root/'localonly').exists()
    (engine.root/'localonly').unlink(); engine.sync()
    assert 'localonly' not in store.files

def test_sdk_store_uses_conditional_operations_and_bounded_config(tmp_path):
    from storage import S3Store
    class Client:
        def put_object(self, **kwargs):
            self.put=kwargs; return {'ETag':'"new"'}
        def get_object(self, **kwargs):
            import io
            self.get=kwargs; return {'Body':io.BytesIO(b'hello')}
        def delete_object(self, **kwargs):
            self.deleted=kwargs
    client=Client()
    store=S3Store({'s3_bucket':'bucket','s3_prefix':'p'},client=client)
    import io, threading
    assert store.upload('a',io.BytesIO(b'hello'),None)=='"new"'
    assert client.put['IfNoneMatch']=='*'
    store.upload('a',io.BytesIO(b'hello'),'"old"')
    assert client.put['IfMatch']=='"old"'
    out=io.BytesIO(); store.download('a',out,'"new"',threading.Event())
    assert client.get['IfMatch']=='"new"' and out.getvalue()==b'hello'
    store.delete('a','"new"'); assert client.deleted['IfMatch']=='"new"'

def test_repeated_failure_is_logged_once_then_as_a_reminder(tmp_path, monkeypatch, caplog):
    import logging
    import sync_engine
    class FailingStore(FakeStore):
        def list(self):
            raise ConnectionError('injected')
    engine = make_engine(tmp_path, FailingStore())
    clock = [1000.0]
    monkeypatch.setattr(sync_engine.time, 'monotonic', lambda: clock[0])
    with caplog.at_level(logging.INFO):
        for _ in range(50):
            engine.sync()
        assert [r.getMessage() for r in caplog.records] == ['ConnectionError']
        clock[0] += sync_engine.REPEAT_LOG_SECONDS
        engine.sync()
        assert caplog.records[-1].getMessage() == 'Still failing: ConnectionError'
        engine.store = FakeStore()
        engine.sync()
        assert caplog.records[-1].getMessage() == 'Previous sync problems resolved'
