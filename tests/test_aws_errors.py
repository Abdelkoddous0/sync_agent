"""AWS failures are explained by code and clock skew, never by provider messages."""
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import subprocess
from unittest.mock import patch

import boto3
from botocore.exceptions import ClientError
from botocore.stub import Stubber

import aws_errors
import authentication
import helpers


def client_error(code, aws_clock_offset_hours=0, message='SECRET-BEARING MESSAGE'):
    aws_now = datetime.now(timezone.utc) + timedelta(hours=aws_clock_offset_hours)
    return ClientError({'Error': {'Code': code, 'Message': message},
                        'ResponseMetadata': {'HTTPHeaders': {'date': format_datetime(aws_now, usegmt=True)}}},
                       'ListObjectsV2')


def test_code_is_shown_but_never_the_message():
    text = aws_errors.describe(client_error('AccessDenied'))
    assert text == 'ClientError(AccessDenied)'
    assert 'SECRET' not in text


def test_wrong_pc_clock_is_explained():
    text = aws_errors.describe(client_error('RequestTimeTooSkewed', aws_clock_offset_hours=2))
    assert text.startswith('ClientError(RequestTimeTooSkewed). This PC clock is 2 h 0 min behind')
    assert 'Set time automatically' in text


def test_small_skew_or_unrelated_code_has_no_clock_hint():
    assert 'clock' not in aws_errors.describe(client_error('SignatureDoesNotMatch'))
    assert 'clock' not in aws_errors.describe(client_error('AccessDenied', aws_clock_offset_hours=2))
    assert aws_errors.describe(ValueError('x')) == 'ValueError'


def test_identity_check_reports_clock_problem(monkeypatch):
    sts = boto3.client('sts', region_name='eu-central-1', aws_access_key_id='offline', aws_secret_access_key='offline')
    aws_now = format_datetime(datetime.now(timezone.utc) + timedelta(hours=2), usegmt=True)
    monkeypatch.setattr(boto3, 'Session', lambda **kw: type('S', (), {'client': lambda self, *a, **k: sts})())
    with Stubber(sts) as stub:
        stub.add_client_error('get_caller_identity', service_error_code='SignatureDoesNotMatch',
                              service_message='Signature expired SECRET', http_status_code=403,
                              response_meta={'HTTPHeaders': {'date': aws_now}})
        valid, message = authentication.verify_identity({'auth_method': 'workload_role', 'region': 'eu-central-1'})
    assert not valid and 'clock is 2 h 0 min behind' in message and 'SECRET' not in message


def test_wizard_key_check_explains_clock_and_wrong_secret():
    failed = subprocess.CompletedProcess([], 254, '', 'An error occurred (SignatureDoesNotMatch) when calling '
                                                     'the GetCallerIdentity operation: SECRET details')
    with patch('aws_cli.ensure_aws_cli', return_value='aws'), patch.object(helpers.subprocess, 'run', return_value=failed):
        with patch('aws_errors.measure_clock_skew', return_value=-7200):
            valid, message = helpers.verify_aws('AKIAOFFLINE', 'secret')
        assert not valid and 'clock is 2 h 0 min behind' in message
        with patch('aws_errors.measure_clock_skew', return_value=3):
            valid, message = helpers.verify_aws('AKIAOFFLINE', 'secret')
        assert 'secret key does not match' in message and 'SECRET' not in message
