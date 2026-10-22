"""Switching back to dedicated static keys must not retain another credential provider."""
import configparser
from unittest.mock import patch
import os
import helpers


def test_static_key_save_removes_only_dedicated_profile_provider_selectors(tmp_path):
    awsconfig=tmp_path/'config'; credentials=tmp_path/'credentials'
    awsconfig.write_text('[profile sync-agent]\nrole_arn = arn:aws:iam::123456789012:role/old\nsource_profile = other\nsso_session = old\ncredential_process = untrusted-unused-helper\naws_session_token = stale\n[profile other]\nregion = us-east-1\n[sso-session shared]\nsso_region = eu-central-1\n')
    credentials.write_text('[sync-agent]\naws_access_key_id = OLD_FIXTURE\naws_secret_access_key = OLD_FIXTURE\naws_session_token = OLD_FIXTURE\n[other]\naws_access_key_id = OTHER_FIXTURE\naws_secret_access_key = OTHER_FIXTURE\n')
    with patch.dict(os.environ,{'AWS_CONFIG_FILE':str(awsconfig),'AWS_SHARED_CREDENTIALS_FILE':str(credentials)}):
        helpers.save_credentials('NEW_FIXTURE','NEW_FIXTURE','eu-central-1')
    parsed=configparser.RawConfigParser(); parsed.read(awsconfig)
    assert set(parsed['profile sync-agent'])=={'region','output'}
    assert parsed['profile other']['region']=='us-east-1'
    assert parsed.has_section('sso-session shared')
    parsed=configparser.RawConfigParser(); parsed.read(credentials)
    assert set(parsed['sync-agent'])=={'aws_access_key_id','aws_secret_access_key'}
    assert parsed['other']['aws_access_key_id']=='OTHER_FIXTURE'
