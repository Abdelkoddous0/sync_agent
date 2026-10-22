"""Explicitly opt-in real S3 conditional-operation acceptance, never part of CI.

Creates only one tiny object under a unique sync-agent-acceptance/<UUID>/ prefix
in an explicitly supplied DISPOSABLE bucket. Charges/versioned delete markers
may remain; never run against valuable data. No credentials are saved here.
"""
import io
import os
import threading
import uuid
import pytest

pytestmark=pytest.mark.skipif(
    os.environ.get('SYNC_AGENT_LIVE_S3')!='I_ACCEPT_TEST_OBJECT_WRITES',
    reason='Live S3 is disabled: requires explicit bucket/profile and write/delete opt-in')


def test_live_s3_conditional_put_get_delete(tmp_path):
    from botocore.exceptions import ClientError
    from config import validate_config
    from storage import S3Store
    bucket=os.environ.get('SYNC_AGENT_LIVE_BUCKET','')
    profile=os.environ.get('SYNC_AGENT_LIVE_PROFILE','')
    method=os.environ.get('SYNC_AGENT_LIVE_AUTH_METHOD','profile')
    assert bucket, 'Supply SYNC_AGENT_LIVE_BUCKET: a disposable non-production bucket'
    assert method in {'profile','sso','roles_anywhere','workload_role'}
    assert profile or method=='workload_role', 'Supply an explicit AWS profile'
    assert not any(os.environ.get(key) for key in ('AWS_ENDPOINT_URL','AWS_ENDPOINT_URL_S3')), 'Custom endpoints are not covered by this AWS acceptance test'
    prefix='sync-agent-acceptance/'+uuid.uuid4().hex
    cfg=validate_config({'workstation_id':'live-acceptance','local_path':str(tmp_path/'local'),
        's3_bucket':bucket,'s3_prefix':prefix,'auth_method':method,
        'aws_profile':None if method=='workload_role' else profile,
        'region':os.environ.get('SYNC_AGENT_LIVE_REGION','eu-central-1'),
        'transfer_timeout':30,'max_retries':1})
    store=S3Store(cfg)
    name='conditional-probe.txt'
    latest=None
    def read(version):
        body=io.BytesIO()
        store.download(name,body,version,threading.Event())
        return body.getvalue()
    def expect_precondition(call):
        with pytest.raises(ClientError) as error:
            call()
        assert error.value.response['ResponseMetadata']['HTTPStatusCode']==412
    try:
        assert store.list()=={}, 'Generated test prefix unexpectedly exists; refusing writes'
        first=store.upload(name,io.BytesIO(b'first test version'),None)
        latest=first
        assert read(first)==b'first test version'
        expect_precondition(lambda:store.upload(name,io.BytesIO(b'must not overwrite'),None))
        assert read(first)==b'first test version'
        second=store.upload(name,io.BytesIO(b'second test version'),first)
        latest=second
        assert second!=first
        expect_precondition(lambda:store.upload(name,io.BytesIO(b'stale update'),first))
        expect_precondition(lambda:read(first))
        expect_precondition(lambda:store.delete(name,first))
        assert read(second)==b'second test version'
        store.delete(name,second)
        latest=None
        assert store.list()=={}
    finally:
        # Only our exact key and last successfully returned ETag; no bulk/unconditional deletion.
        if latest is not None:
            store.delete(name,latest)
