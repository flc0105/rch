import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from rch_notifier.cli import _build_parser, main


class CliTests(unittest.TestCase):
    def test_tray_is_disabled_by_default(self):
        args = _build_parser().parse_args([])
        self.assertFalse(args.tray)

    def test_tray_can_be_enabled_explicitly(self):
        args = _build_parser().parse_args(['--tray'])
        self.assertTrue(args.tray)

    def _run_main(self, extra_args):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / 'config.json'
            config_path.write_text('{}', encoding='utf-8')
            config = SimpleNamespace(server_url='http://server:8085', backend='auto', sound=True)
            backend = Mock(active_mode='test')
            runtime = Mock()
            patches = (
                patch('rch_notifier.cli.load_config', return_value=config),
                patch('rch_notifier.cli.create_notification_backend', return_value=backend),
                patch('rch_notifier.cli.CursorState', return_value=Mock()),
                patch('rch_notifier.cli.NotificationStreamRuntime', return_value=runtime),
                patch('rch_notifier.cli._run_headless', return_value=11),
                patch('rch_notifier.cli._run_macos_menu', return_value=22),
                patch('rch_notifier.cli.platform.system', return_value='Darwin'),
            )
            entered = [item.__enter__() for item in patches]
            try:
                result = main(['--config', str(config_path), *extra_args])
                return result, runtime, entered[4], entered[5]
            finally:
                for item in reversed(patches):
                    item.__exit__(None, None, None)

    def test_macos_without_tray_uses_original_headless_runtime(self):
        result, runtime, run_headless, run_menu = self._run_main([])
        self.assertEqual(11, result)
        run_headless.assert_called_once_with(runtime)
        run_menu.assert_not_called()

    def test_macos_with_tray_uses_menu_bar_runtime(self):
        result, runtime, run_headless, run_menu = self._run_main(['--tray'])
        self.assertEqual(22, result)
        run_headless.assert_not_called()
        run_menu.assert_called_once()
        self.assertIs(runtime, run_menu.call_args.args[2])


if __name__ == '__main__':
    unittest.main()
