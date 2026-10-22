import unittest
from unittest.mock import patch

class WizardTests(unittest.TestCase):
    def test_settings_write_holds_singleton_lock(self):
        import config
        import runtime
        import wizard
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)/'SyncAgent'
            cfg = {'workstation_id':'ws22','local_path':str(Path(folder)/'files'),
                   's3_bucket':'example-bucket','s3_prefix':'ws22'}
            with patch.object(config,'DATA_DIR',data), patch.object(config,'CONFIG_PATH',data/'config.json'), \
                 patch.object(config,'LOG_DIR',data/'logs'), patch('commands.cmd_stop'), \
                 patch.object(config,'save_config',side_effect=lambda c: self.assertTrue(runtime.is_running(data))):
                wizard.apply_settings(cfg)
            self.assertFalse(runtime.is_running(data))

    def test_cancel_does_not_stop_or_save(self):
        import wizard
        with patch.object(wizard, 'collect_settings', return_value=({'valid': True}, None)), \
             patch.object(wizard, 'confirm', return_value=False), \
             patch.object(wizard, 'apply_settings') as apply, \
             patch.object(wizard, 'ensure_aws_cli'):
            self.assertFalse(wizard.run_setup())
        apply.assert_not_called()

    def test_failed_validation_does_not_stop_agent(self):
        import wizard
        with patch('commands.cmd_stop') as stop:
            with self.assertRaises(ValueError):
                wizard.apply_settings({'workstation_id':'bad id'})
        stop.assert_not_called()

class ReconfigureTests(unittest.TestCase):
    def test_cancel_leaves_settings_unsaved(self):
        import reconfigure
        with patch('config.load_config', return_value={'workstation_id':'ws22'}), \
             patch('reconfigure.ask', return_value='q'), \
             patch('reconfigure.finish_settings') as finish, \
             patch('reconfigure.ensure_aws_cli'):
            self.assertFalse(reconfigure.run_reconfigure())
        finish.assert_not_called()

if __name__ == '__main__': unittest.main()
