"""Offline CLI/setup regressions."""
import configparser
import importlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch


class SetupTests(unittest.TestCase):
    def test_save_credentials_preserves_other_profiles_without_command_arguments(self):
        import ast
        source = Path(__file__).resolve().parents[1]/'helpers.py'
        self.assertIn('save_credentials', [n.name for n in ast.parse(source.read_text()).body if isinstance(n,ast.FunctionDef)])
        import helpers
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            credentials = root/'credentials'
            awsconfig = root/'config'
            credentials.write_text('[default]\naws_access_key_id = OTHER\naws_secret_access_key = OTHER_SECRET\n')
            with patch.dict(os.environ, {'AWS_SHARED_CREDENTIALS_FILE':str(credentials),'AWS_CONFIG_FILE':str(awsconfig)}):
                helpers.save_credentials('NEW_ACCESS', 'NEW_SECRET', 'eu-central-1', 'SESSION')
            parsed = configparser.RawConfigParser()
            parsed.read(credentials)
            self.assertEqual(parsed['default']['aws_access_key_id'],'OTHER')
            self.assertEqual(parsed['sync-agent']['aws_secret_access_key'],'NEW_SECRET')
            self.assertEqual(parsed['sync-agent']['aws_session_token'],'SESSION')
            parsed.read(awsconfig)
            self.assertEqual(parsed['profile sync-agent']['region'],'eu-central-1')

    def test_status_command_is_available_without_optional_gui_dependencies(self):
        import commands
        self.assertTrue(callable(getattr(commands, 'cmd_status', None)))


if __name__=='__main__':
    unittest.main()
