"""Use real botocore service models and Stubber; never contact an AWS endpoint."""
import io
from pathlib import Path
import threading
import boto3
from botocore.exceptions import ClientError
from botocore.stub import Stubber, ANY
from packaging.requirements import Requirement
import pytest
from storage import S3Store


def test_distribution_requires_verified_conditional_sdk_versions():
    lines=(Path(__file__).resolve().parents[1]/'requirements.txt').read_text().splitlines()
    reqs={r.name:r for line in lines if line and not line.startswith('#') for r in [Requirement(line)]}
    for name in ['boto3','botocore']:
        assert name in reqs
        assert '1.43.117' in reqs[name].specifier
        assert '1.43.116' not in reqs[name].specifier


def test_real_sdk_conditional_requests_validate_without_network():
    client=boto3.client('s3',region_name='us-east-1',aws_access_key_id='offline',aws_secret_access_key='offline')
    store=S3Store({'s3_bucket':'example-bucket','s3_prefix':'ws22'},client=client)
    with Stubber(client) as stub:
        for expected,condition in [(None,{'IfNoneMatch':'*'}),('"old"',{'IfMatch':'"old"'})]:
            stub.add_response('put_object',{'ETag':'"new"'},
                              {'Bucket':'example-bucket','Key':'ws22/a','Body':ANY,'ContentLength':3,**condition})
            assert store.upload('a',io.BytesIO(b'abc'),expected)=='"new"'
        stub.add_response('get_object',{'Body':io.BytesIO(b'abc'),'ContentLength':3},
                          {'Bucket':'example-bucket','Key':'ws22/a','IfMatch':'"new"'})
        target=io.BytesIO(); store.download('a',target,'"new"',threading.Event())
        assert target.getvalue()==b'abc'
        stub.add_response('delete_object',{}, {'Bucket':'example-bucket','Key':'ws22/a','IfMatch':'"new"'})
        store.delete('a','"new"')
        stub.add_client_error('put_object',service_error_code='PreconditionFailed',http_status_code=412,
                              expected_params={'Bucket':'example-bucket','Key':'ws22/a','Body':ANY,'ContentLength':3,'IfMatch':'"old"'})
        with pytest.raises(ClientError): store.upload('a',io.BytesIO(b'abc'),'"old"')
        stub.assert_no_pending_responses()
