"""Offline authentication regressions; never use real profiles or credentials."""
import pytest
import config


def settings(tmp_path, **updates):
    return dict(workstation_id='auth-test', local_path=str(tmp_path/'files'),
                s3_bucket='example-test-bucket', s3_prefix='acceptance', **updates)


@pytest.mark.parametrize('method,profile', [
    ('access_keys','sync-agent'), ('profile','company-profile'), ('sso','company-sso'),
    ('roles_anywhere','company-certificate'), ('workload_role',None)])
def test_config_retains_auth_selection(tmp_path, method, profile):
    cfg=config.validate_config(settings(tmp_path, auth_method=method, aws_profile=profile))
    assert cfg['auth_method']==method
    assert cfg['aws_profile']==profile


def test_legacy_config_defaults_to_access_keys(tmp_path):
    cfg=config.validate_config(settings(tmp_path))
    assert cfg['auth_method']=='access_keys'
    assert cfg['aws_profile']=='sync-agent'


@pytest.mark.parametrize('method,profile', [
    ('unsupported','sync-agent'), ('access_keys','other'), ('workload_role','sync-agent'),
    ('profile',None), ('profile',''), ('sso','bad/name'), ('profile','space name'),
    ('profile','x'*129), ('roles_anywhere','profile\nname'), ('profile','é')])
def test_config_rejects_invalid_auth_selection(tmp_path, method, profile):
    with pytest.raises(ValueError):
        config.validate_config(settings(tmp_path, auth_method=method, aws_profile=profile))


@pytest.mark.parametrize('method,profile', [
    ('access_keys','sync-agent'), ('profile','company-profile'), ('sso','company-sso'),
    ('roles_anywhere','company-certificate'), ('workload_role',None)])
def test_sdk_session_kwargs_and_storage_use_selected_mode(tmp_path, monkeypatch, method, profile):
    import authentication
    import boto3
    from unittest.mock import Mock
    from storage import S3Store
    cfg=config.validate_config(settings(tmp_path, auth_method=method, aws_profile=profile))
    expected={'region_name':cfg['region']}
    if method!='workload_role':
        expected['profile_name']=profile
    assert authentication.session_kwargs(cfg)==expected
    session=Mock()
    monkeypatch.setattr(boto3,'Session',session)
    S3Store(cfg)
    session.assert_called_once_with(**expected)
    assert session.return_value.client.call_args.args==('s3',)


@pytest.fixture
def aws_files(tmp_path, monkeypatch):
    config_file=tmp_path/'aws-config'
    credentials=tmp_path/'aws-credentials'
    config_file.write_text('',encoding='utf-8')
    credentials.write_text('',encoding='utf-8')
    monkeypatch.setenv('AWS_CONFIG_FILE',str(config_file))
    monkeypatch.setenv('AWS_SHARED_CREDENTIALS_FILE',str(credentials))
    monkeypatch.setenv('AWS_EC2_METADATA_DISABLED','true')
    return config_file,credentials


SSO_PROFILE='''[profile selected]
sso_session = organization
sso_account_id = 123456789012
sso_role_name = TestRole
[sso-session organization]
sso_start_url = https://example.awsapps.com/start
sso_region = eu-central-1
'''


@pytest.mark.parametrize('method,contents', [
    ('sso',SSO_PROFILE),
    ('sso','[profile selected]\nsso_start_url = https://example.awsapps.com/start\nsso_region = eu-central-1\nsso_account_id = 123456789012\nsso_role_name = TestRole\n'),
    ('roles_anywhere','[profile selected]\ncredential_process = trusted-helper credential-process --certificate cert.pem\n'),
    ('profile','[profile selected]\ncredential_process = trusted-helper\n')])
def test_profile_validation_reads_only_local_configuration(aws_files, monkeypatch, method, contents):
    import authentication
    import botocore.session
    from unittest.mock import Mock
    aws_files[0].write_text(contents,encoding='utf-8')
    forbidden=Mock(side_effect=AssertionError('credential resolution/process execution forbidden'))
    monkeypatch.setattr(botocore.session.Session,'get_credentials',forbidden)
    monkeypatch.setattr(botocore.session.Session,'create_client',forbidden)
    monkeypatch.setattr('subprocess.run',forbidden)
    authentication.validate_auth_profile({'auth_method':method,'aws_profile':'selected'})
    forbidden.assert_not_called()


@pytest.mark.parametrize('method,contents,credentials', [
    ('profile','',''),
    ('sso','[profile selected]\nsso_session = missing\nsso_account_id = 123456789012\nsso_role_name = Role\n',''),
    ('sso',SSO_PROFILE.replace('sso_role_name = TestRole\n',''),''),
    ('sso',SSO_PROFILE,'[selected]\naws_access_key_id = offline\naws_secret_access_key = offline\n'),
    ('sso',SSO_PROFILE.replace('[profile selected]','[profile selected]\ncredential_process = shadow-helper'),''),
    ('roles_anywhere','[profile selected]\nregion = eu-central-1\n',''),
    ('roles_anywhere','[profile selected]\ncredential_process = helper\nrole_arn = shadow\n',''),
    ('roles_anywhere','[profile selected]\ncredential_process = helper\nsso_session = shadow\n',''),
    ('roles_anywhere','[profile selected]\ncredential_process = helper\n','[selected]\naws_access_key_id = offline\naws_secret_access_key = offline\n')])
def test_profile_validation_rejects_missing_or_shadowed_provider(aws_files, method, contents, credentials):
    import authentication
    aws_files[0].write_text(contents,encoding='utf-8')
    aws_files[1].write_text(credentials,encoding='utf-8')
    with pytest.raises(ValueError):
        authentication.validate_auth_profile({'auth_method':method,'aws_profile':'selected'})


def test_workload_validation_does_not_read_profiles(monkeypatch):
    import authentication
    import botocore.session
    from unittest.mock import Mock
    forbidden=Mock(side_effect=AssertionError('must not inspect profiles'))
    monkeypatch.setattr(botocore.session,'Session',forbidden)
    authentication.validate_auth_profile({'auth_method':'workload_role','aws_profile':None})
    forbidden.assert_not_called()


def test_sso_login_explicit_bounded_and_shell_free(aws_files, monkeypatch):
    import authentication
    import aws_cli
    from unittest.mock import Mock
    aws_files[0].write_text(SSO_PROFILE,encoding='utf-8')
    ensure=Mock(return_value='C:/trusted/aws.exe')
    run=Mock()
    monkeypatch.setattr(aws_cli,'ensure_aws_cli',ensure)
    monkeypatch.setattr('subprocess.run',run)
    authentication.login_sso({'auth_method':'sso','aws_profile':'selected'})
    ensure.assert_called_once_with(interactive=False)
    run.assert_called_once_with(['C:/trusted/aws.exe','sso','login','--profile','selected',
                                 '--no-cli-pager'],check=True,timeout=300)


@pytest.mark.parametrize('method',['access_keys','profile','roles_anywhere','workload_role'])
def test_login_rejects_non_sso_without_launch(method, monkeypatch):
    import authentication
    from unittest.mock import Mock
    run=Mock()
    monkeypatch.setattr('subprocess.run',run)
    with pytest.raises(ValueError,match='SSO'):
        authentication.login_sso({'auth_method':method})
    run.assert_not_called()


def test_sso_login_invalid_profile_never_launches(aws_files, monkeypatch):
    import authentication
    from unittest.mock import Mock
    run=Mock()
    monkeypatch.setattr('subprocess.run',run)
    with pytest.raises(ValueError):
        authentication.login_sso({'auth_method':'sso','aws_profile':'selected'})
    run.assert_not_called()


def test_sso_login_failure_is_sanitized(aws_files, monkeypatch, caplog):
    import authentication
    import aws_cli
    import subprocess
    from unittest.mock import Mock
    aws_files[0].write_text(SSO_PROFILE,encoding='utf-8')
    monkeypatch.setattr(aws_cli,'ensure_aws_cli',lambda **kw:'aws')
    secret='DO_NOT_LOG_AUTHORIZATION_TOKEN'
    monkeypatch.setattr(subprocess,'run',Mock(side_effect=RuntimeError(secret)))
    with pytest.raises(RuntimeError) as error:
        authentication.login_sso({'auth_method':'sso','aws_profile':'selected'})
    assert secret not in str(error.value)
    assert secret not in caplog.text


@pytest.mark.parametrize('method,profile,contents', [
    ('access_keys','sync-agent','[profile sync-agent]\nregion = eu-central-1\n'),
    ('profile','selected','[profile selected]\nregion = eu-central-1\n'),
    ('sso','selected',SSO_PROFILE),
    ('roles_anywhere','selected','[profile selected]\ncredential_process = trusted-helper\n'),
    ('workload_role',None,'')])
def test_identity_check_uses_selected_session_and_bounded_sts(aws_files, monkeypatch, method, profile, contents):
    import authentication
    import boto3
    from botocore.stub import Stubber
    from unittest.mock import Mock
    aws_files[0].write_text(contents,encoding='utf-8')
    client=boto3.client('sts',region_name='eu-central-1',
                        aws_access_key_id='offline',aws_secret_access_key='offline')
    cfg={'auth_method':method,'aws_profile':profile,'region':'eu-central-1'}
    session=Mock()
    session.return_value.client.return_value=client
    monkeypatch.setattr(boto3,'Session',session)
    with Stubber(client) as stub:
        stub.add_response('get_caller_identity',{
            'Account':'123456789012','Arn':'arn:aws:iam::123456789012:user/test',
            'UserId':'offline-test'}, {})
        valid,message=authentication.verify_identity(cfg)
        stub.assert_no_pending_responses()
    assert valid is True
    assert '123456789012' in message
    assert 'arn:aws:iam::123456789012:user/test' in message
    assert 'S3' in message
    session.assert_called_once_with(**authentication.session_kwargs(cfg))
    args=session.return_value.client.call_args
    assert args.args==('sts',)
    sdk_config=args.kwargs['config']
    assert sdk_config.connect_timeout==5
    assert sdk_config.read_timeout==10
    assert sdk_config.retries['total_max_attempts']==1


def test_identity_failure_never_discloses_provider_exception(monkeypatch, caplog):
    import authentication
    import boto3
    from unittest.mock import Mock
    secret='DO_NOT_LOG_PROVIDER_TOKEN'
    monkeypatch.setattr(boto3,'Session',Mock(side_effect=RuntimeError(secret)))
    valid,message=authentication.verify_identity({'auth_method':'workload_role','aws_profile':None})
    assert valid is False
    assert secret not in message
    assert secret not in caplog.text


def test_invalid_auth_profile_is_rejected_before_identity_client(aws_files, monkeypatch):
    import authentication
    import boto3
    from unittest.mock import Mock
    session=Mock()
    monkeypatch.setattr(boto3,'Session',session)
    valid,message=authentication.verify_identity({'auth_method':'sso','aws_profile':'missing'})
    assert valid is False
    session.assert_not_called()


@pytest.mark.parametrize('account,arn', [
    ('unexpected\nDO_NOT_ECHO_RESPONSE','arn:aws:iam::123456789012:user/test'),
    ('123456789012','arn:aws:iam::123456789012:user/test\nDO_NOT_ECHO_RESPONSE')])
def test_identity_does_not_echo_malformed_principal_fields(monkeypatch, account, arn):
    import authentication
    import boto3
    from unittest.mock import Mock
    session=Mock()
    session.return_value.client.return_value.get_caller_identity.return_value={'Account':account,'Arn':arn}
    monkeypatch.setattr(boto3,'Session',session)
    valid,message=authentication.verify_identity({'auth_method':'workload_role','aws_profile':None})
    assert valid is True
    assert 'DO_NOT_ECHO_RESPONSE' not in message
    assert '\n' not in message
