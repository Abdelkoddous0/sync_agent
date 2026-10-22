"""Configuration regressions; never touch the user's configuration."""
import importlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {'LOCALAPPDATA':str(self.root), 'ProgramData':str(self.root)})
        self.env.start()
        import config
        self.config = importlib.reload(config)
        self.addCleanup(self.restore_environment)

    def restore_environment(self):
        self.env.stop()
        importlib.reload(self.config)

    def valid(self):
        return {'workstation_id':'ws22', 'local_path':str(self.root/'files'),
                's3_bucket':'example-bucket', 's3_prefix':'workstations/ws22', 'region':'eu-central-1'}

    def test_validate_defaults_and_reject_shell_ids(self):
        c = self.config.validate_config(self.valid())
        self.assertEqual(c['aws_profile'], 'sync-agent')
        self.assertFalse(c['delete_on_s3'])
        self.assertFalse(c['delete_local'])
        for value in ['bad id', 'bad"&whoami', "bad'", '../bad', '']:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.config.validate_config({**self.valid(), 'workstation_id':value})

    def test_symlink_root_is_rejected_before_normalization(self):
        actual = self.root/'actual'
        actual.mkdir()
        alias = self.root/'alias'
        try:
            alias.symlink_to(actual,target_is_directory=True)
        except OSError:
            self.skipTest('Symlink creation requires platform privileges')
        with self.assertRaisesRegex(ValueError,'link|reparse'):
            self.config.validate_config({**self.valid(),'local_path':str(alias)})

    def test_secrets_and_unknown_fields_cannot_enter_settings_or_status(self):
        checked = self.config.validate_config({**self.valid(),'aws_secret_access_key':'sentinel-secret'})
        self.assertNotIn('aws_secret_access_key',checked)

    def test_invalid_numeric_values_fail(self):
        for key,value in [('poll_interval',0),('max_retries',0),('debounce_secs',-1),('transfer_timeout',True)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.config.validate_config({**self.valid(),key:value})

    def test_overlong_startup_command_is_rejected_before_registry_changes(self):
        registry=MagicMock()
        with patch('config.os.name','nt'), patch.dict('sys.modules',{'winreg':registry}), patch('config.launch_command',return_value=['C:\\'+'x'*270+'\\SyncAgent.exe','--background']):
            result=self.config.register_startup()
        self.assertFalse(result)
        registry.CreateKey.assert_not_called()

    def test_atomic_save_preserves_original_if_replace_fails(self):
        self.config.save_config(self.valid())
        original = self.config.CONFIG_PATH.read_bytes()
        with patch('config.os.replace',side_effect=OSError('injected')):
            with self.assertRaises(OSError): self.config.save_config({**self.valid(),'poll_interval':40})
        self.assertEqual(self.config.CONFIG_PATH.read_bytes(),original)
        self.assertEqual(list(self.config.DATA_DIR.glob('*.tmp')),[])


if __name__ == '__main__':
    unittest.main()
