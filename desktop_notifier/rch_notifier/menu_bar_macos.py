import logging
import webbrowser
from urllib.parse import urlparse


logger = logging.getLogger('rch_notifier')


def _server_display(server_url: str) -> str:
    parsed = urlparse(str(server_url or '').strip())
    return parsed.hostname or parsed.netloc or str(server_url or '').strip()


class MacOSMenuBar:
    """Minimal AppKit menu-bar shell for the standalone RCH notifier.

    AppKit is imported lazily so the shared notifier package remains importable
    on Windows/Linux. The Cocoa event loop always runs on the process main
    thread; SSE status callbacks are marshalled to that thread with callAfter.
    """

    def __init__(self, *, server_url: str, backend, runtime):
        self.server_url = str(server_url or '').strip()
        self.backend = backend
        self.runtime = runtime
        self._app = None
        self._status_item = None
        self._status_menu_item = None
        self._server_menu_item = None
        self._retry_menu_item = None
        self._target = None
        self._AppHelper = None
        self._NSImage = None
        self._menu = None
        self._pending_connection = (False, None)

    def _load_cocoa(self):
        from AppKit import (
            NSApplication,
            NSApplicationActivationPolicyAccessory,
            NSImage,
            NSMenu,
            NSMenuItem,
            NSStatusBar,
            NSVariableStatusItemLength,
        )
        from Foundation import NSObject
        from PyObjCTools import AppHelper

        return {
            'NSApplication': NSApplication,
            'NSApplicationActivationPolicyAccessory': NSApplicationActivationPolicyAccessory,
            'NSImage': NSImage,
            'NSMenu': NSMenu,
            'NSMenuItem': NSMenuItem,
            'NSStatusBar': NSStatusBar,
            'NSVariableStatusItemLength': NSVariableStatusItemLength,
            'NSObject': NSObject,
            'AppHelper': AppHelper,
        }

    def run(self):
        cocoa = self._load_cocoa()
        NSApplication = cocoa['NSApplication']
        NSApplicationActivationPolicyAccessory = cocoa['NSApplicationActivationPolicyAccessory']
        NSMenu = cocoa['NSMenu']
        NSMenuItem = cocoa['NSMenuItem']
        NSStatusBar = cocoa['NSStatusBar']
        NSVariableStatusItemLength = cocoa['NSVariableStatusItemLength']
        NSObject = cocoa['NSObject']
        self._AppHelper = cocoa['AppHelper']
        self._NSImage = cocoa['NSImage']

        owner = self

        class MenuTarget(NSObject):
            def openRCH_(self, _sender):
                owner.open_rch()

            def testNotification_(self, _sender):
                owner.test_notification()

            def reconnect_(self, _sender):
                owner.reconnect()

            def quit_(self, _sender):
                owner.quit()

        self._target = MenuTarget.alloc().init()
        self._app = NSApplication.sharedApplication()
        self._app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

        self._status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
        self._configure_status_button(connected=False)

        menu = NSMenu.alloc().init()
        self._menu = menu
        heading = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_('RCH Notifier', None, '')
        heading.setEnabled_(False)
        menu.addItem_(heading)
        menu.addItem_(NSMenuItem.separatorItem())

        self._status_menu_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_('○ Disconnected', None, '')
        self._status_menu_item.setEnabled_(False)
        menu.addItem_(self._status_menu_item)

        self._server_menu_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            f'Server: {_server_display(self.server_url)}',
            None,
            '',
        )
        self._server_menu_item.setEnabled_(False)
        menu.addItem_(self._server_menu_item)

        self._retry_menu_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_('Retrying...', None, '')
        self._retry_menu_item.setEnabled_(False)
        self._retry_menu_item.setHidden_(True)
        menu.addItem_(self._retry_menu_item)
        menu.addItem_(NSMenuItem.separatorItem())

        menu.addItem_(self._action_item(NSMenuItem, 'Open RCH', 'openRCH:'))
        menu.addItem_(self._action_item(NSMenuItem, 'Test Notification', 'testNotification:'))
        menu.addItem_(self._action_item(NSMenuItem, 'Reconnect', 'reconnect:'))
        menu.addItem_(NSMenuItem.separatorItem())
        menu.addItem_(self._action_item(NSMenuItem, 'Quit', 'quit:'))

        self._status_item.setMenu_(menu)
        self._apply_connection(*self._pending_connection)
        logger.info('macOS menu bar started')
        self._AppHelper.runEventLoop()

    def _action_item(self, NSMenuItem, title: str, selector: str):
        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, selector, '')
        item.setTarget_(self._target)
        return item

    def _configure_status_button(self, *, connected: bool):
        button = self._status_item.button()
        if button is None:
            return
        button.setToolTip_('RCH Notifier')
        symbol_name = 'bell' if connected else 'bell.slash'
        image = None
        try:
            image = self._NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                symbol_name,
                'RCH Notifier',
            )
        except Exception:
            image = None
        if image is not None:
            try:
                image.setTemplate_(True)
            except Exception:
                pass
            button.setImage_(image)
            button.setTitle_('')
        else:
            button.setImage_(None)
            button.setTitle_('RCH')

    def update_connection(self, connected: bool, retry_seconds=None):
        self._pending_connection = (bool(connected), retry_seconds)
        if self._AppHelper is None:
            return
        self._AppHelper.callAfter(self._apply_connection, bool(connected), retry_seconds)

    def _apply_connection(self, connected: bool, retry_seconds=None):
        if self._status_menu_item is None:
            return
        self._status_menu_item.setTitle_('● Connected' if connected else '○ Disconnected')
        if connected or retry_seconds is None:
            self._retry_menu_item.setHidden_(True)
        else:
            self._retry_menu_item.setTitle_(f'Retrying in {int(retry_seconds)}s...')
            self._retry_menu_item.setHidden_(False)
        self._configure_status_button(connected=connected)

    def open_rch(self):
        try:
            webbrowser.open(self.server_url)
        except Exception as exc:
            logger.warning('Failed to open RCH in the browser: %s', exc)

    def test_notification(self):
        try:
            self.backend.notify({
                'id': 'menu-test',
                'type': 'info',
                'title': 'RCH Notifier',
                'message': 'Desktop notification test succeeded.',
            })
            logger.info('Menu-bar test notification submitted')
        except Exception as exc:
            logger.warning('Test notification failed: %s', exc, exc_info=logger.isEnabledFor(logging.DEBUG))

    def reconnect(self):
        logger.info('Manual reconnect requested from menu bar')
        self.runtime.reconnect()

    def request_quit(self):
        if self._AppHelper is None:
            return
        self._AppHelper.callAfter(self.quit)

    def quit(self):
        logger.info('RCH Desktop Notifier quitting')
        self.runtime.stop()
        if self._AppHelper is not None:
            self._AppHelper.stopEventLoop()
