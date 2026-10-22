import unittest
from unittest.mock import Mock, patch

class TrayTests(unittest.TestCase):
    def test_cancel_maintenance_keeps_agent_running(self):
        import tray
        event = Mock()
        with patch.object(tray,'confirm_action',return_value=False), patch('subprocess.Popen') as launch:
            tray.launch_maintenance('--uninstall',event)
        launch.assert_not_called()
        event.set.assert_not_called()

    def test_source_command_includes_main_script(self):
        import tray
        import config
        event = Mock()
        with patch.object(tray,'confirm_action',return_value=True), patch('subprocess.Popen') as launch:
            tray.launch_maintenance('--reconfigure',event)
        self.assertEqual(launch.call_args.args[0],config.launch_command('--reconfigure','--pause'))
        event.set.assert_not_called()

if __name__ == '__main__': unittest.main()
