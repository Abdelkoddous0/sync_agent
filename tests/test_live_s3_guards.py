"""Exercise live-test refusal guards OFFLINE without an S3 client."""
import importlib.util
from pathlib import Path
from unittest.mock import patch
import pytest


@pytest.mark.parametrize('settings,reason',[
    ({},'disposable non-production bucket'),
    ({'SYNC_AGENT_LIVE_BUCKET':'example-test-bucket'},'explicit AWS profile'),
    ({'SYNC_AGENT_LIVE_BUCKET':'example-test-bucket','SYNC_AGENT_LIVE_PROFILE':'test-profile',
      'AWS_ENDPOINT_URL':'https://invalid.example'},'Custom endpoints'),
])
def test_live_acceptance_refuses_missing_scope_before_client_creation(tmp_path,monkeypatch,settings,reason):
    for key in ('SYNC_AGENT_LIVE_BUCKET','SYNC_AGENT_LIVE_PROFILE','SYNC_AGENT_LIVE_AUTH_METHOD',
                'AWS_ENDPOINT_URL','AWS_ENDPOINT_URL_S3'):
        monkeypatch.delenv(key,raising=False)
    for key,value in settings.items(): monkeypatch.setenv(key,value)
    path=Path(__file__).with_name('test_live_s3.py')
    spec=importlib.util.spec_from_file_location('live_guard_target',path)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    with patch('storage.S3Store') as store:
        with pytest.raises(AssertionError,match=reason):
            module.test_live_s3_conditional_put_get_delete(tmp_path)
    store.assert_not_called()
