import importlib
import unittest
from unittest.mock import Mock, patch

class EntryTests(unittest.TestCase):
    def test_status_propagates_result_without_bootstrap(self):
        import main
        with patch('commands.cmd_status', return_value=0) as status:
            self.assertEqual(main.main(['--status']), 0)
        status.assert_called_once_with()

    def test_background_without_config_does_not_prompt(self):
        import main
        path = Mock()
        path.exists.return_value = False
        with patch('config.CONFIG_PATH', path):
            self.assertEqual(main.main(['--background']), 1)

if __name__ == '__main__': unittest.main()
