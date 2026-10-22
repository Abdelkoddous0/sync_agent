"""Offline regressions for first-installation usability and Windows-specific defects."""
import io
import json
import os
from pathlib import Path
import threading
from unittest.mock import patch

import pytest

import config
import wizard

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('script', ['install.ps1', 'uninstall.ps1', 'ensure_aws_cli.ps1'])
def test_lifecycle_scripts_open_process_handle_before_reading_exit_code(script):
    # Windows PowerShell 5.1: Start-Process -PassThru leaves ExitCode $null otherwise,
    # which made every real installation fail its "--status" check.
    text = (ROOT / 'scripts' / script).read_text(encoding='utf-8')
    assert text.count('Start-Process') == text.count('$null = $process.Handle')


@pytest.mark.parametrize('script', ['install.ps1', 'uninstall.ps1'])
def test_missing_startup_value_is_read_without_powershell_51_exception(script):
    # Get-ItemPropertyValue -ErrorAction SilentlyContinue still throws on 5.1 when the
    # value is missing, which failed every first installation.
    text = (ROOT / 'scripts' / script).read_text(encoding='utf-8')
    assert 'Get-ItemPropertyValue' in text and 'SilentlyContinue' not in text.split('Get-ItemPropertyValue', 1)[1].split('\n', 1)[0]
    assert text.count('Get-ItemPropertyValue') == 1


def test_redirected_output_cannot_crash_on_console_symbols():
    import subprocess
    import sys
    result = subprocess.run([sys.executable, '-c', 'import ui; ui.banner(); ui.ok("done")'], cwd=ROOT / 'src',
                            capture_output=True, env={**os.environ, 'PYTHONIOENCODING': 'cp1252'}, timeout=60)
    assert result.returncode == 0, result.stderr


def test_wizard_reprompts_invalid_paths_instead_of_aborting(tmp_path):
    cfg = {'workstation_id': 'ws22'}
    answers = ['relative\\folder', str(tmp_path / 'files'), 's3://Bad_Bucket', 's3://good-bucket/', 'team//../ws22', '/team/ws22/']
    with patch.object(wizard, 'ask', side_effect=answers), patch.object(wizard, 'err') as err:
        wizard.edit_paths(cfg)
    assert cfg['local_path'] == str(tmp_path / 'files')
    assert cfg['s3_bucket'] == 'good-bucket'
    assert cfg['s3_prefix'] == 'team/ws22'
    assert err.call_count == 3


def test_region_typo_is_reasked():
    cfg = {}
    with patch.object(wizard, 'ask', side_effect=['Frankfurt', 'eu-central-1', '4']), \
         patch.object(wizard, 'validate_auth_profile'), patch.object(wizard, 'err') as err:
        wizard.edit_credentials(cfg)
    assert cfg['region'] == 'eu-central-1' and err.call_count == 1


def test_first_install_defaults_to_entering_access_keys():
    defaults = []
    def confirm(prompt, default=True):
        defaults.append(default)
        return True
    with patch.object(wizard, 'list_profiles', return_value=[]), patch.object(wizard, 'confirm', confirm), \
         patch.object(wizard, 'ask', side_effect=['AKIAOFFLINE', 'offline-secret', '']), \
         patch.object(wizard, 'verify_aws', return_value=(True, 'AWS account 123456789012')):
        result = wizard._edit_access_credentials({'region': 'eu-central-1'})
    assert defaults[0] is True
    assert result == ('AKIAOFFLINE', 'offline-secret', 'eu-central-1', '')


def test_rejected_access_keys_can_be_reentered():
    with patch.object(wizard, 'list_profiles', return_value=[]), \
         patch.object(wizard, 'confirm', side_effect=[True, True]), \
         patch.object(wizard, 'ask', side_effect=['WRONG', 'wrong', '', 'RIGHT', 'right', '']), \
         patch.object(wizard, 'verify_aws', side_effect=[(False, 'denied'), (True, 'ok')]):
        assert wizard._edit_access_credentials({'region': 'eu-central-1'})[:2] == ('RIGHT', 'right')


def test_missing_profile_can_be_corrected():
    cfg = {}
    with patch.object(wizard, 'ask', side_effect=['eu-central-1', '2', 'typo', 'company-sso']), \
         patch.object(wizard, 'list_profiles', return_value=['company-sso']), \
         patch.object(wizard, 'confirm', return_value=True), patch.object(wizard, 'err'), \
         patch.object(wizard, 'validate_auth_profile', side_effect=[ValueError('missing'), None]):
        wizard.edit_credentials(cfg)
    assert cfg['aws_profile'] == 'company-sso'


def test_agent_is_started_without_sharing_the_setup_console(tmp_path):
    with patch.object(wizard, 'confirm', return_value=True), patch.object(wizard, 'apply_settings'), \
         patch.object(wizard, 'subprocess') as processes:
        wizard.finish_settings({'auth_method': 'access_keys'}, None)
    kwargs = processes.Popen.call_args.kwargs
    assert kwargs['env'][config.DETACHED_ENV] == '1'
    if os.name == 'nt':
        import subprocess
        assert kwargs['creationflags'] & subprocess.CREATE_NO_WINDOW


def test_status_reports_invalid_configuration_without_failing(tmp_path, monkeypatch):
    import commands
    monkeypatch.setattr(config, 'CONFIG_PATH', tmp_path / 'config.json')
    (tmp_path / 'config.json').write_text('{"workstation_id": "bad id"}', encoding='utf-8')
    assert commands.cmd_status() == 0


def test_background_startup_failure_is_visible_in_status(tmp_path, monkeypatch):
    import main
    monkeypatch.setattr(config, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(config, 'CONFIG_PATH', tmp_path / 'config.json')
    (tmp_path / 'config.json').write_text('{}', encoding='utf-8')
    monkeypatch.setattr('aws_cli.ensure_aws_cli', lambda **kw: (_ for _ in ()).throw(RuntimeError('AWS CLI not found')))
    assert main.main(['--background']) == 1
    report = json.loads((tmp_path / 'status.json').read_text(encoding='utf-8'))
    assert report['errors'] == ['Startup failed: AWS CLI not found']


class SlowBody:
    """Many small blocks; the whole transfer outlasts transfer_timeout, no block stalls."""
    def __init__(self, clock, blocks):
        self.clock, self.blocks = clock, blocks
    def read(self, size):
        self.clock[0] += 5
        return self.blocks.pop(0) if self.blocks else b''
    def close(self):
        pass


def test_large_download_is_limited_by_stalls_not_total_duration(monkeypatch):
    import storage
    clock = [0.0]
    monkeypatch.setattr(storage.time, 'monotonic', lambda: clock[0])
    class Client:
        def get_object(self, **kwargs):
            return {'Body': SlowBody(clock, [b'x'] * 100), 'ContentLength': 100}
    store = storage.S3Store({'s3_bucket': 'example-bucket', 's3_prefix': 'p', 'transfer_timeout': 10}, client=Client())
    target = io.BytesIO()
    store.download('a', target, '"etag"', threading.Event())
    assert target.getvalue() == b'x' * 100
    class Stalled:
        def get_object(self, **kwargs):
            body = SlowBody(clock, [b'x'])
            body.read = lambda size: clock.__setitem__(0, clock[0] + 60) or b'x'
            return {'Body': body}
    with pytest.raises(TimeoutError):
        storage.S3Store({'s3_bucket': 'example-bucket', 's3_prefix': 'p', 'transfer_timeout': 10},
                        client=Stalled()).download('a', io.BytesIO(), '"etag"', threading.Event())


def test_scan_reuses_hash_only_for_unchanged_settled_files(tmp_path):
    from sync_engine import SyncEngine
    root = tmp_path / 'local'
    root.mkdir()
    old, fresh = root / 'old.txt', root / 'fresh.txt'
    old.write_bytes(b'settled')
    fresh.write_bytes(b'recent')
    hour_ago = os.stat(old).st_mtime - 3600
    os.utime(old, (hour_ago, hour_ago))
    class Store:
        def list(self):
            return {}
    engine = SyncEngine({'local_path': str(root), 's3_bucket': 'example-bucket', 's3_prefix': 'p'},
                        store=Store(), state_path=tmp_path / 'baseline.json')
    first = engine._locals()
    hashed = []
    original = engine._fingerprint
    engine._fingerprint = lambda name: hashed.append(name) or original(name)
    assert engine._locals() == first
    assert hashed == ['fresh.txt']
    old.write_bytes(b'changed')
    os.utime(old, (hour_ago + 1, hour_ago + 1))
    hashed.clear()
    assert engine._locals()['old.txt'] != first['old.txt']
    assert 'old.txt' in hashed
