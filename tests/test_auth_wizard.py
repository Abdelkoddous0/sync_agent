"""Authentication menu regressions: collecting/cancelling must not log in or write AWS files."""
from unittest.mock import patch
import pytest
import wizard


@pytest.mark.parametrize('choice,method,profile',[
    ('2','sso','company-sso'),('3','roles_anywhere','company-certificate'),
    ('4','workload_role',None),('5','profile','existing-profile')])
def test_collects_auth_options_without_authentication_side_effects(choice,method,profile):
    cfg={}
    answers=['eu-central-1',choice]+([profile] if profile else [])
    with patch.object(wizard,'ask',side_effect=answers), \
         patch.object(wizard,'confirm',return_value=False), \
         patch.object(wizard,'verify_aws',return_value=(True,'offline fixture')), \
         patch.object(wizard,'validate_auth_profile',create=True) as validate, \
         patch.object(wizard,'login_sso',create=True) as login, \
         patch.object(wizard,'verify_identity',create=True) as verify, \
         patch.object(wizard,'save_credentials') as save:
        assert wizard.edit_credentials(cfg) is None
    assert cfg['auth_method']==method
    assert cfg['aws_profile']==profile
    validate.assert_called_once_with(cfg)
    login.assert_not_called(); verify.assert_not_called(); save.assert_not_called()


def test_cancel_sso_save_does_not_login_or_stop():
    cfg={'auth_method':'sso','aws_profile':'company-sso'}
    with patch.object(wizard,'confirm',return_value=False), \
         patch.object(wizard,'apply_settings') as apply, \
         patch.object(wizard,'login_sso',create=True) as login:
        assert wizard.finish_settings(cfg,None) is False
    apply.assert_not_called(); login.assert_not_called()


def test_sso_login_occurs_only_after_approved_save():
    cfg={'auth_method':'sso','aws_profile':'company-sso'}
    order=[]
    with patch.object(wizard,'confirm',side_effect=[True,True,False]), \
         patch.object(wizard,'subprocess') as processes, \
         patch.object(wizard,'apply_settings',side_effect=lambda *a: order.append('save')), \
         patch.object(wizard,'login_sso',create=True,side_effect=lambda *a: order.append('login')), \
         patch.object(wizard,'verify_identity',create=True,return_value=(True,'AWS identity verified')):
        assert wizard.finish_settings(cfg,None) is True
    assert order==['save','login']


def test_profile_validation_happens_before_stop(tmp_path):
    cfg={'workstation_id':'ws22','local_path':str(tmp_path/'files'),
         's3_bucket':'example-bucket','s3_prefix':'workstations/ws22',
         'auth_method':'sso','aws_profile':'company-sso'}
    with patch.object(wizard.config,'validate_config',return_value=cfg), \
         patch.object(wizard,'validate_auth_profile',create=True,side_effect=ValueError('Invalid auth profile')), \
         patch('runtime.RuntimeGuard'), \
         patch.object(wizard,'_apply_settings_locked'), \
         patch('commands.cmd_stop') as stop:
        with pytest.raises(ValueError,match='Invalid auth profile'): wizard.apply_settings(cfg)
    stop.assert_not_called()
