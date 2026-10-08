import unittest
from unittest.mock import Mock, patch

from rch_notifier.menu_bar_macos import MacOSMenuBar


class _AllocObject:
    @classmethod
    def alloc(cls):
        return cls()

    def init(self):
        return self


class _FakeNSObject(_AllocObject):
    pass


class _FakeMenuItem(_AllocObject):
    def __init__(self):
        self.title = ''
        self.action = None
        self.enabled = True
        self.hidden = False
        self.target = None
        self.separator = False

    def initWithTitle_action_keyEquivalent_(self, title, action, _key):
        self.title = title
        self.action = action
        return self

    @classmethod
    def separatorItem(cls):
        item = cls()
        item.separator = True
        return item

    def setEnabled_(self, value):
        self.enabled = bool(value)

    def setHidden_(self, value):
        self.hidden = bool(value)

    def setTitle_(self, value):
        self.title = value

    def setTarget_(self, value):
        self.target = value


class _FakeMenu(_AllocObject):
    def __init__(self):
        self.items = []

    def addItem_(self, item):
        self.items.append(item)


class _FakeButton:
    def __init__(self):
        self.title = ''
        self.image = None
        self.tooltip = ''

    def setToolTip_(self, value):
        self.tooltip = value

    def setImage_(self, value):
        self.image = value

    def setTitle_(self, value):
        self.title = value


class _FakeStatusItem:
    def __init__(self):
        self._button = _FakeButton()
        self.menu = None

    def button(self):
        return self._button

    def setMenu_(self, menu):
        self.menu = menu


class _FakeStatusBarInstance:
    def __init__(self):
        self.item = _FakeStatusItem()

    def statusItemWithLength_(self, _length):
        return self.item


class _FakeStatusBar:
    instance = _FakeStatusBarInstance()

    @classmethod
    def systemStatusBar(cls):
        return cls.instance


class _FakeApplicationInstance:
    def __init__(self):
        self.policy = None

    def setActivationPolicy_(self, policy):
        self.policy = policy


class _FakeApplication:
    instance = _FakeApplicationInstance()

    @classmethod
    def sharedApplication(cls):
        return cls.instance


class _FakeImageObject:
    def __init__(self, name):
        self.name = name
        self.template = False

    def setTemplate_(self, value):
        self.template = bool(value)


class _FakeImage:
    @classmethod
    def imageWithSystemSymbolName_accessibilityDescription_(cls, name, _description):
        return _FakeImageObject(name)


class _FakeAppHelper:
    ran = 0
    stopped = 0

    @classmethod
    def runEventLoop(cls):
        cls.ran += 1

    @classmethod
    def stopEventLoop(cls):
        cls.stopped += 1

    @classmethod
    def callAfter(cls, callback, *args):
        callback(*args)


class MenuBarTests(unittest.TestCase):
    def _cocoa(self):
        _FakeStatusBar.instance = _FakeStatusBarInstance()
        _FakeApplication.instance = _FakeApplicationInstance()
        _FakeAppHelper.ran = 0
        _FakeAppHelper.stopped = 0
        return {
            'NSApplication': _FakeApplication,
            'NSApplicationActivationPolicyAccessory': 1,
            'NSImage': _FakeImage,
            'NSMenu': _FakeMenu,
            'NSMenuItem': _FakeMenuItem,
            'NSStatusBar': _FakeStatusBar,
            'NSVariableStatusItemLength': -1,
            'NSObject': _FakeNSObject,
            'AppHelper': _FakeAppHelper,
        }

    def test_menu_layout_and_connection_status(self):
        backend = Mock()
        runtime = Mock()
        menu = MacOSMenuBar(
            server_url='http://192.168.1.20:8085',
            backend=backend,
            runtime=runtime,
        )
        menu._load_cocoa = self._cocoa
        menu.run()

        titles = [item.title for item in menu._menu.items if not item.separator]
        self.assertEqual([
            'RCH Notifier',
            '○ Disconnected',
            'Server: 192.168.1.20',
            'Retrying...',
            'Open RCH',
            'Test Notification',
            'Reconnect',
            'Quit',
        ], titles)
        self.assertTrue(menu._retry_menu_item.hidden)

        menu.update_connection(False, 8)
        self.assertEqual('○ Disconnected', menu._status_menu_item.title)
        self.assertEqual('Retrying in 8s...', menu._retry_menu_item.title)
        self.assertFalse(menu._retry_menu_item.hidden)

        menu.update_connection(True, None)
        self.assertEqual('● Connected', menu._status_menu_item.title)
        self.assertTrue(menu._retry_menu_item.hidden)
        self.assertEqual('bell', menu._status_item.button().image.name)

    def test_menu_actions_reuse_existing_backend_and_runtime(self):
        backend = Mock()
        runtime = Mock()
        menu = MacOSMenuBar(server_url='http://server:8085', backend=backend, runtime=runtime)
        menu._load_cocoa = self._cocoa
        menu.run()

        with patch('rch_notifier.menu_bar_macos.webbrowser.open') as open_browser:
            menu.open_rch()
        open_browser.assert_called_once_with('http://server:8085')

        menu.test_notification()
        backend.notify.assert_called_once()
        menu.reconnect()
        runtime.reconnect.assert_called_once_with()
        menu.quit()
        runtime.stop.assert_called_once_with()
        self.assertEqual(1, _FakeAppHelper.stopped)


if __name__ == '__main__':
    unittest.main()
