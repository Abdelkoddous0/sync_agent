"""Explicitly opt-in end-to-end sync against REAL S3, never part of CI.

Runs the real SyncEngine and S3Store against a unique sync-agent-acceptance/e2e-<UUID>/
prefix in an explicitly supplied disposable bucket. Opt-in, bucket, profile and region
use the same environment variables as test_live_s3.py. Every object it creates is
removed at the end with conditional deletes of the exact ETags it observed.
"""
import io
import os
import threading
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get('SYNC_AGENT_LIVE_S3') != 'I_ACCEPT_TEST_OBJECT_WRITES',
    reason='Live S3 is disabled: requires explicit bucket/profile and write/delete opt-in')


def test_live_end_to_end_sync(tmp_path):
    from config import validate_config
    from storage import S3Store
    from sync_engine import SyncEngine
    bucket = os.environ.get('SYNC_AGENT_LIVE_BUCKET', '')
    profile = os.environ.get('SYNC_AGENT_LIVE_PROFILE', '')
    method = os.environ.get('SYNC_AGENT_LIVE_AUTH_METHOD', 'profile')
    assert bucket, 'Supply SYNC_AGENT_LIVE_BUCKET: a disposable non-production bucket'
    assert profile or method == 'workload_role', 'Supply an explicit AWS profile'
    assert not any(os.environ.get(k) for k in ('AWS_ENDPOINT_URL', 'AWS_ENDPOINT_URL_S3')), 'Custom endpoints are not covered'
    local = tmp_path / 'local'
    local.mkdir()
    cfg = validate_config({'workstation_id': 'live-e2e', 'local_path': str(local), 's3_bucket': bucket,
                           's3_prefix': 'sync-agent-acceptance/e2e-' + uuid.uuid4().hex,
                           'auth_method': method, 'aws_profile': None if method == 'workload_role' else profile,
                           'region': os.environ.get('SYNC_AGENT_LIVE_REGION', 'eu-central-1'),
                           'transfer_timeout': 30, 'max_retries': 2})
    store = S3Store(cfg)
    state = tmp_path / 'baseline.json'

    def engine():
        return SyncEngine(cfg, store=store, state_path=state)

    def remote(name):
        body = io.BytesIO()
        store.download(name, body, store.list()[name], threading.Event())
        return body.getvalue()

    def put_remote(name, data):
        return store.upload(name, io.BytesIO(data), store.list().get(name))

    try:
        assert store.list() == {}, 'Generated test prefix unexpectedly exists; refusing writes'
        sync = engine()
        # First-sync conflict: the same name on both sides before any baseline.
        (local / 'both.txt').write_bytes(b'local first')
        put_remote('both.txt', b'remote first')
        # 1. New local file is uploaded; new remote file is downloaded (nested folder).
        (local / 'up.txt').write_bytes(b'from the PC')
        put_remote('folder/down.txt', b'from S3')
        report = sync.sync()
        assert not report['errors'], report
        assert 'both.txt: untracked on both sides' in report['conflicts']
        assert remote('up.txt') == b'from the PC'
        assert (local / 'folder' / 'down.txt').read_bytes() == b'from S3'
        assert (local / 'both.txt').read_bytes() == b'local first' and remote('both.txt') == b'remote first'
        # 2. Edits travel both ways.
        (local / 'up.txt').write_bytes(b'edited on the PC')
        put_remote('folder/down.txt', b'edited in S3')
        report = sync.sync()
        assert not report['errors'], report
        assert remote('up.txt') == b'edited on the PC'
        assert (local / 'folder' / 'down.txt').read_bytes() == b'edited in S3'
        # 3. Both sides edited: conflict, nothing overwritten.
        (local / 'up.txt').write_bytes(b'PC edit during conflict')
        put_remote('up.txt', b'S3 edit during conflict')
        report = sync.sync()
        assert 'up.txt: both sides changed' in report['conflicts']
        assert (local / 'up.txt').read_bytes() == b'PC edit during conflict'
        assert remote('up.txt') == b'S3 edit during conflict'
        # 4. Default deletion behaviour: a local deletion does not delete in S3 ...
        (local / 'folder' / 'down.txt').unlink()
        report = sync.sync()
        assert not report['errors'], report
        assert remote('folder/down.txt') == b'edited in S3'
        # ... and is remembered, also after a restart (no resurrection).
        restarted = engine()
        report = restarted.sync()
        assert not (local / 'folder' / 'down.txt').exists()
        assert 'up.txt: both sides changed' in report['conflicts']
        assert not report['errors'], report
    finally:
        # Exact keys under our unique prefix only, each with the ETag just listed.
        for name, etag in store.list().items():
            store.delete(name, etag)
        assert store.list() == {}
