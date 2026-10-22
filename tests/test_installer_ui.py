"""Offline one-file installer, import and console presentation tests."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

import installer
import ui
import wizard


def settings(tmp_path):
    return {'workstation_id': 'ws22', 'local_path': str(tmp_path / 'files'),
            's3_bucket': 'example-bucket', 's3_prefix': 'workstations/ws22'}


def test_default_workstation_id_is_valid_for_unusual_hostnames():
    with patch.dict('os.environ', {'COMPUTERNAME': 'Büro PC#7.local'}):
        value = wizard.default_workstation_id()
    assert value == 'B-ro-PC-7-local'
    with patch.dict('os.environ', {'COMPUTERNAME': '###'}):
        assert wizard.default_workstation_id() == 'workstation'


def test_settings_table_never_shows_unknown_fields(tmp_path, capsys):
    ui.settings_table({**settings(tmp_path), 'aws_secret_access_key': 'NEVER_PRINT'})
    output = capsys.readouterr().out
    assert 'example-bucket' in output and 'NEVER_PRINT' not in output


def test_import_cancel_does_not_apply(tmp_path):
    path = tmp_path / 'prepared.json'
    path.write_text(json.dumps(settings(tmp_path)))
    with patch.object(wizard, 'confirm', return_value=False), \
         patch.object(wizard, 'apply_settings') as apply, patch.object(wizard, 'ensure_aws_cli') as ensure:
        assert wizard.run_import(path) is False
    apply.assert_not_called(); ensure.assert_not_called()


def test_import_yes_applies_without_credentials_and_defaults_workstation(tmp_path):
    data = settings(tmp_path)
    del data['workstation_id']
    path = tmp_path / 'prepared.json'
    path.write_text(json.dumps(data))
    with patch.object(wizard, 'apply_settings') as apply, patch.object(wizard, 'ensure_aws_cli'), \
         patch.object(wizard, 'subprocess') as processes, patch.object(wizard, 'default_workstation_id', return_value='pc1'):
        assert wizard.run_import(path, assume_yes=True) is True
    (cfg,), kwargs = apply.call_args
    assert cfg['workstation_id'] == 'pc1' and not kwargs
    processes.Popen.assert_called_once()


def test_import_rejects_invalid_settings_before_stopping(tmp_path):
    path = tmp_path / 'prepared.json'
    path.write_text(json.dumps({**settings(tmp_path), 's3_bucket': 's3://bad'}))
    with patch.object(wizard, 'apply_settings') as apply:
        with pytest.raises(ValueError, match='bucket'):
            wizard.run_import(path, assume_yes=True)
    apply.assert_not_called()


def test_installer_refuses_non_windows_and_incomplete_payload(tmp_path):
    with patch.object(installer, 'windows', return_value=False):
        assert installer.main(['--yes', '--source', str(tmp_path)]) == 1
    with patch.object(installer, 'windows', return_value=True), \
         patch.object(installer.subprocess, 'run') as run:
        assert installer.main(['--yes', '--source', str(tmp_path)]) == 1
    run.assert_not_called()


def payload(tmp_path):
    source = tmp_path / 'payload'
    source.mkdir()
    for name in installer.PAYLOAD_FILES:
        (source / name).write_text('offline fixture')
    return source


def test_installer_cancel_changes_nothing(tmp_path):
    with patch.object(installer, 'windows', return_value=True), \
         patch.object(installer, 'confirm', return_value=False), \
         patch.object(installer, 'find_prepared_config', return_value=None), \
         patch.object(installer.subprocess, 'run') as run:
        assert installer.install(installer.parse_args(['--source', str(payload(tmp_path))])) == 2
    run.assert_not_called()


def test_installer_delegates_to_script_then_setup(tmp_path):
    source = payload(tmp_path)
    calls = []
    def fake_run(command, **kwargs):
        calls.append(command)
        return installer.subprocess.CompletedProcess(command, 0, '', '')
    with patch.object(installer, 'windows', return_value=True), \
         patch.object(installer, 'existing_settings', return_value=None), \
         patch.object(installer, 'find_prepared_config', return_value=None), \
         patch.object(installer, 'confirm', return_value=True), \
         patch.object(installer.subprocess, 'run', side_effect=fake_run):
        assert installer.install(installer.parse_args(['--source', str(source)])) == 0
    script, setup = calls
    assert str(source / 'install.ps1') in script and '-Yes' in script and '-NoStartup' in script
    assert setup[-1] == '--setup'


def test_installer_keeps_existing_autostart_and_imports_prepared_settings(tmp_path):
    source = payload(tmp_path)
    prepared = tmp_path / 'SyncAgent.config.json'
    prepared.write_text('{}')
    calls = []
    with patch.object(installer, 'windows', return_value=True), \
         patch.object(installer, 'existing_settings', return_value={'autostart': True}), \
         patch.object(installer.subprocess, 'run',
                      side_effect=lambda c, **k: calls.append(c) or installer.subprocess.CompletedProcess(c, 0, '', '')):
        assert installer.install(installer.parse_args(['--yes', '--source', str(source), '--config', str(prepared)])) == 0
    script, imported = calls
    assert '-NoStartup' not in script
    assert imported[1:] == ['--import-config', str(prepared), '--yes']


def test_build_produces_single_file_installer_with_full_payload():
    text = (Path(__file__).resolve().parents[1] / 'build.bat').read_text()
    assert text.index('--name SyncAgent ') < text.index('--name SyncAgentSetup')
    assert '--onefile' in text and 'dist\\SyncAgent;payload' in text and 'installer.py' in text
