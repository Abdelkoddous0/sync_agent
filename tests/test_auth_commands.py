"""Offline entrypoint auth command tests: no real browser, AWS, helper or process."""
from types import SimpleNamespace
from unittest.mock import Mock, patch
import sys
import pytest
import config
import main


@pytest.mark.parametrize('flag,function',[('--login','login_sso'),('--check-auth','verify_identity')])
def test_explicit_auth_command_uses_selected_configuration(flag,function):
    cfg={'auth_method':'sso','aws_profile':'company-sso','region':'eu-central-1'}
    auth=SimpleNamespace(login_sso=Mock(),verify_identity=Mock(return_value=(True,'AWS identity verified')))
    with patch.dict(sys.modules,{'authentication':auth}), \
         patch.object(config,'CONFIG_PATH') as path, \
         patch.object(config,'load_config',return_value=cfg), \
         patch.object(config,'show_console'):
        path.exists.return_value=True
        assert main.main([flag])==0
    getattr(auth,function).assert_called_once_with(cfg)
    if flag=='--check-auth': auth.login_sso.assert_not_called()


@pytest.mark.parametrize('flag',['--login','--check-auth'])
def test_unconfigured_auth_command_never_runs_setup_or_login(flag):
    auth=SimpleNamespace(login_sso=Mock(),verify_identity=Mock())
    with patch.dict(sys.modules,{'authentication':auth}), \
         patch.object(config,'CONFIG_PATH') as path, \
         patch('wizard.run_setup') as setup:
        path.exists.return_value=False
        assert main.main([flag])==1
    setup.assert_not_called(); auth.login_sso.assert_not_called(); auth.verify_identity.assert_not_called()


def test_auth_check_failure_sets_failure_exit_code():
    auth=SimpleNamespace(verify_identity=Mock(return_value=(False,'AWS identity verification failed')))
    with patch.dict(sys.modules,{'authentication':auth}), \
         patch.object(config,'CONFIG_PATH') as path, \
         patch.object(config,'load_config',return_value={'auth_method':'profile'}), \
         patch.object(config,'show_console'):
        path.exists.return_value=True
        assert main.main(['--check-auth'])==1


def test_provider_error_cannot_leak_through_debug_logging(tmp_path, monkeypatch, caplog, capsys):
    import logging
    import agent
    from botocore.exceptions import CredentialRetrievalError
    secret='DO_NOT_LOG_PROVIDER_OUTPUT'
    caplog.set_level(logging.DEBUG)
    cfg={'auth_method':'profile','aws_profile':'selected'}
    marker=tmp_path/'config.json'
    marker.write_text('{}',encoding='utf-8')
    monkeypatch.setattr(config,'CONFIG_PATH',marker)
    monkeypatch.setattr(config,'load_config',lambda:cfg)
    monkeypatch.setattr(config,'hide_console',lambda:None)
    monkeypatch.setattr('aws_cli.ensure_aws_cli',lambda **kw:'aws')
    def fail(cfg):
        raise CredentialRetrievalError(provider='custom-process',error_msg=secret)
    monkeypatch.setattr(agent,'run_agent',fail)
    assert main.main(['--background'])==1
    output=capsys.readouterr()
    assert secret not in output.out+output.err
    assert secret not in caplog.text


def test_saved_sso_config_reaches_real_backend_from_cli(tmp_path, monkeypatch):
    import boto3
    from botocore.stub import Stubber
    shared=tmp_path/'aws-config'
    shared.write_text('[profile selected]\nsso_session = org\nsso_account_id = 123456789012\n'
                      'sso_role_name = TestRole\n[sso-session org]\n'
                      'sso_start_url = https://example.awsapps.com/start\nsso_region = eu-central-1\n',encoding='utf-8')
    credentials=tmp_path/'credentials'
    credentials.write_text('',encoding='utf-8')
    monkeypatch.setenv('AWS_CONFIG_FILE',str(shared))
    monkeypatch.setenv('AWS_SHARED_CREDENTIALS_FILE',str(credentials))
    monkeypatch.setenv('AWS_EC2_METADATA_DISABLED','true')
    monkeypatch.setattr(config,'DATA_DIR',tmp_path/'state')
    monkeypatch.setattr(config,'CONFIG_PATH',tmp_path/'state'/'config.json')
    monkeypatch.setattr(config,'LOG_DIR',tmp_path/'state'/'logs')
    monkeypatch.setattr(config,'show_console',lambda:None)
    config.save_config({'workstation_id':'cli-test','local_path':str(tmp_path/'files'),
                        's3_bucket':'example-test-bucket','s3_prefix':'test-prefix',
                        'auth_method':'sso','aws_profile':'selected'})
    monkeypatch.setattr('aws_cli.ensure_aws_cli',lambda **kw:'aws')
    with patch('subprocess.run') as login:
        assert main.main(['--login'])==0
        assert login.call_args.args[0]==['aws','sso','login','--profile','selected','--no-cli-pager']
    sts=boto3.client('sts',region_name='eu-central-1',aws_access_key_id='offline',aws_secret_access_key='offline')
    session=Mock()
    session.return_value.client.return_value=sts
    monkeypatch.setattr(boto3,'Session',session)
    with Stubber(sts) as stub:
        stub.add_response('get_caller_identity',{'Account':'123456789012',
            'Arn':'arn:aws:iam::123456789012:user/test','UserId':'offline'}, {})
        assert main.main(['--check-auth'])==0
        stub.assert_no_pending_responses()
    session.assert_called_once_with(profile_name='selected',region_name='eu-central-1')
