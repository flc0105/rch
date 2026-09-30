import re
import sys
import time

from client.jobs.core.job import Job
from client.runtime.sdk import events


JOB_METADATA = {
    'name': 'wechat_macos_message_event',
    'display_name': 'WeChat macOS Message Probe',
    'description': (
        'Experimentally watch WeChat menu-bar badge changes through Accessibility and, '
        'when enabled, probe Notification Center banners for WeChat message text.'
    ),
    'platforms': ['mac'],
    'params': [
        {
            'name': 'interval',
            'type': 'number',
            'default': 1.0,
            'min': 0.5,
            'max': 30,
            'description': 'Polling interval in seconds.',
        },
        {
            'name': 'monitor_banners',
            'type': 'boolean',
            'default': True,
            'description': 'Also probe Notification Center accessibility banners for WeChat text.',
        },
        {
            'name': 'debug_ax',
            'type': 'boolean',
            'default': True,
            'description': 'Send compact AXExtrasMenuBar/notification probe details to the Job log.',
        },
    ],
}

_WECHAT_BUNDLE_HINTS = ('com.tencent.xinwechat', 'com.tencent.wechat')
_WECHAT_NAME_HINTS = ('wechat', 'weixin', '微信')
_BANNER_SUBROLES = {
    'AXNotificationCenterBanner',
    'AXNotificationCenterAlert',
    'AXNotificationCenterNotification',
    'AXNotificationCenterBannerWindow',
    'AXNotificationCenterAlertStack',
}
_BADGE_PATTERNS = (
    re.compile(r'^\s*(\d{1,4})\s*$'),
    re.compile(r'(\d{1,4})\s*(?:unread|条(?:新)?消息|消息)', re.IGNORECASE),
    re.compile(r'(?:unread|未读|消息)[^\d]{0,8}(\d{1,4})', re.IGNORECASE),
)


def _safe_text(value) -> str:
    return '' if value is None else str(value).strip()


def _ax_attr(ax, element, name: str):
    try:
        error, value = ax.AXUIElementCopyAttributeValue(element, name, None)
        return value if int(error) == 0 else None
    except Exception:
        return None


def _ax_children(ax, element) -> list:
    value = _ax_attr(ax, element, 'AXVisibleChildren')
    if not value:
        value = _ax_attr(ax, element, 'AXChildren')
    try:
        return list(value or [])
    except Exception:
        return []


def _ax_row(ax, element, depth: int = 0) -> dict:
    return {
        'depth': depth,
        'role': _safe_text(_ax_attr(ax, element, 'AXRole')),
        'subrole': _safe_text(_ax_attr(ax, element, 'AXSubrole')),
        'title': _safe_text(_ax_attr(ax, element, 'AXTitle')),
        'description': _safe_text(_ax_attr(ax, element, 'AXDescription')),
        'value': _safe_text(_ax_attr(ax, element, 'AXValue')),
        'help': _safe_text(_ax_attr(ax, element, 'AXHelp')),
        'identifier': _safe_text(_ax_attr(ax, element, 'AXIdentifier')),
    }


def _walk_ax_entries(ax, root, *, max_depth: int = 5, max_nodes: int = 180):
    entries = []
    pending = [(root, 0)]
    while pending and len(entries) < max_nodes:
        element, depth = pending.pop(0)
        entries.append((element, _ax_row(ax, element, depth)))
        if depth >= max_depth:
            continue
        pending.extend((child, depth + 1) for child in _ax_children(ax, element))
    return entries


def _walk_ax(ax, root, *, max_depth: int = 5, max_nodes: int = 180) -> list[dict]:
    return [row for _, row in _walk_ax_entries(ax, root, max_depth=max_depth, max_nodes=max_nodes)]


def _row_texts(row: dict) -> list[str]:
    result = []
    for key in ('title', 'description', 'value', 'help', 'identifier'):
        value = _safe_text(row.get(key))
        if value and value not in result:
            result.append(value)
    return result


def _extract_badge_count(rows: list[dict]) -> tuple[int | None, dict | None]:
    for row in rows:
        role = _safe_text(row.get('role'))
        if role and role not in {'AXMenuBarItem', 'AXMenuExtra', 'AXStaticText', 'AXGroup'}:
            continue
        for value in _row_texts(row):
            for pattern in _BADGE_PATTERNS:
                match = pattern.search(value)
                if not match:
                    continue
                try:
                    count = int(match.group(1))
                except Exception:
                    continue
                if 0 <= count <= 9999:
                    return count, row
    return None, None


def _compact_row(row: dict) -> str:
    return (
        f"role={row.get('role')!r} subrole={row.get('subrole')!r} "
        f"title={row.get('title')!r} desc={row.get('description')!r} "
        f"value={row.get('value')!r} help={row.get('help')!r} id={row.get('identifier')!r}"
    )


def _wechat_running_app(workspace):
    for app in list(workspace.runningApplications() or []):
        name = _safe_text(app.localizedName())
        bundle = _safe_text(app.bundleIdentifier()).casefold()
        lowered = name.casefold()
        if any(hint in bundle for hint in _WECHAT_BUNDLE_HINTS):
            return app
        if any(hint in lowered for hint in _WECHAT_NAME_HINTS):
            return app
    return None


def _notification_center_app(workspace):
    for app in list(workspace.runningApplications() or []):
        bundle = _safe_text(app.bundleIdentifier()).casefold()
        if bundle == 'com.apple.notificationcenterui':
            return app
    return None


class WechatMacosMessageEvent(Job):
    def __init__(self):
        super().__init__()
        self._last_badge_count = None
        self._badge_initialized = False
        self._last_extra_signature = None
        self._last_banner_signatures = set()
        self._last_emit_at = 0.0

    def _load_frameworks(self):
        from Cocoa import NSWorkspace
        import ApplicationServices as AX

        return NSWorkspace.sharedWorkspace(), AX

    def _menu_probe(self, workspace, ax) -> dict:
        app = _wechat_running_app(workspace)
        if app is None:
            return {'running': False, 'rows': [], 'count': None, 'matched_row': None, 'pid': 0}

        pid = int(app.processIdentifier())
        root = ax.AXUIElementCreateApplication(pid)
        extras = _ax_attr(ax, root, 'AXExtrasMenuBar')
        if extras is None:
            # Legacy fallback: some applications expose menu extras directly under root.
            rows = [row for row in _walk_ax(ax, root, max_depth=2, max_nodes=80)
                    if row.get('role') in {'AXMenuBarItem', 'AXMenuExtra'}]
        else:
            rows = _walk_ax(ax, extras, max_depth=4, max_nodes=120)

        count, matched_row = _extract_badge_count(rows)
        return {
            'running': True,
            'pid': pid,
            'app_name': _safe_text(app.localizedName()),
            'bundle_id': _safe_text(app.bundleIdentifier()),
            'rows': rows,
            'count': count,
            'matched_row': matched_row,
        }

    def _banner_probe(self, workspace, ax) -> list[dict]:
        app = _notification_center_app(workspace)
        if app is None:
            return []
        root = ax.AXUIElementCreateApplication(int(app.processIdentifier()))
        entries = _walk_ax_entries(ax, root, max_depth=7, max_nodes=450)
        banners = []
        for element, row in entries:
            if row.get('subrole') not in _BANNER_SUBROLES:
                continue
            banner_rows = _walk_ax(ax, element, max_depth=5, max_nodes=90)
            texts = []
            seen = set()
            for banner_row in banner_rows:
                for value in _row_texts(banner_row):
                    if value and value not in seen:
                        seen.add(value)
                        texts.append(value)
            lowered = ' | '.join(texts).casefold()
            if not any(hint in lowered for hint in _WECHAT_NAME_HINTS):
                continue
            banners.append({
                'texts': texts[:24],
                'subroles': sorted({
                    item.get('subrole') for item in banner_rows
                    if item.get('subrole')
                }),
            })
        return banners

    def _emit_badge_increase(self, old_count, new_count, probe):
        message = f'WeChat unread badge: {old_count} -> {new_count}'
        data = {
            'source': 'macos_menu_bar_badge',
            'previous_count': old_count,
            'unread_count': new_count,
            'app_name': probe.get('app_name') or 'WeChat',
            'bundle_id': probe.get('bundle_id') or '',
            'pid': int(probe.get('pid') or 0),
            'matched': probe.get('matched_row') or {},
        }
        events.emit('app.wechat.message_received', data=data, message=message)
        self._last_emit_at = time.monotonic()
        self.send_to_server(1, f'Device event emitted: {message}', 0)

    def _emit_banner(self, banner: dict):
        texts = [str(value) for value in banner.get('texts') or [] if str(value).strip()]
        signature = tuple(texts)
        if not signature or signature in self._last_banner_signatures:
            return
        self._last_banner_signatures.add(signature)
        if len(self._last_banner_signatures) > 20:
            self._last_banner_signatures = {signature}

        # Prefer the last non-app-name text as a compact preview.
        preview = ''
        for value in reversed(texts):
            lowered = value.casefold()
            if any(hint == lowered for hint in _WECHAT_NAME_HINTS):
                continue
            preview = value
            break
        message = 'WeChat notification received' + (f': {preview}' if preview else '')
        events.emit(
            'app.wechat.message_received',
            data={'source': 'macos_notification_banner', 'texts': texts, 'subroles': banner.get('subroles') or []},
            message=message,
        )
        self._last_emit_at = time.monotonic()
        self.send_to_server(1, f'Device event emitted: {message}', 0)

    def run(self):
        if sys.platform != 'darwin':
            self._report_state('error', status=0, text='WeChat macOS Message Probe is macOS-only')
            self.mark_stopped()
            return

        self.mark_running()
        failed = False
        interval = float(self.get_job_param('interval', 1.0) or 1.0)
        monitor_banners = bool(self.get_job_param('monitor_banners', True))
        debug_ax = bool(self.get_job_param('debug_ax', True))

        try:
            workspace, ax = self._load_frameworks()
            trusted = bool(ax.AXIsProcessTrusted())
            self.send_to_server(1, f'WeChat macOS message probe started; accessibility_trusted={trusted}', 0)
            if not trusted:
                self.send_to_server(
                    0,
                    'Accessibility permission is required for the RCH client process (System Settings -> Privacy & Security -> Accessibility).',
                    0,
                )

            while not self.stop_event.is_set():
                probe = self._menu_probe(workspace, ax)
                rows = probe.get('rows') or []
                count = probe.get('count')
                signature = tuple(
                    (_safe_text(row.get('role')), tuple(_row_texts(row)))
                    for row in rows
                    if _row_texts(row)
                )

                if debug_ax and signature != self._last_extra_signature:
                    self.send_to_server(
                        1,
                        f'WeChat AXExtrasMenuBar changed: running={probe.get("running")} pid={probe.get("pid")} '
                        f'badge={count!r} rows={len(rows)}',
                        0,
                    )
                    for row in rows[:30]:
                        if _row_texts(row) or row.get('role') in {'AXMenuBarItem', 'AXMenuExtra'}:
                            self.send_to_server(1, 'AX EXTRA ' + _compact_row(row), 0)
                    self._last_extra_signature = signature

                if probe.get('running'):
                    if not self._badge_initialized:
                        self._last_badge_count = count
                        self._badge_initialized = True
                        self.send_to_server(1, f'WeChat badge baseline: {count!r}', 0)
                    elif count != self._last_badge_count:
                        old_count = self._last_badge_count
                        self._last_badge_count = count
                        self.send_to_server(1, f'WeChat badge changed: {old_count!r} -> {count!r}', 0)
                        if count is not None and count > int(old_count or 0):
                            try:
                                self._emit_badge_increase(old_count, count, probe)
                            except Exception as exc:
                                self.send_to_server(0, f'Badge Device event emit failed: {exc}', 0)
                else:
                    self._badge_initialized = False
                    self._last_badge_count = None

                if monitor_banners:
                    try:
                        banners = self._banner_probe(workspace, ax)
                        for banner in banners:
                            # Avoid a second notification if the badge path emitted almost simultaneously.
                            if time.monotonic() - self._last_emit_at < 2.5:
                                continue
                            self._emit_banner(banner)
                    except Exception as exc:
                        if debug_ax:
                            self.send_to_server(0, f'Notification banner probe failed: {exc}', 0)

                self.stop_event.wait(interval)
        except Exception as exc:
            failed = True
            self.is_running = False
            self.stop_event.set()
            self._report_state('error', status=0, text=str(exc))
            self.send_to_server(0, f'WeChat macOS message probe failed: {exc}', 1)
        finally:
            if not failed:
                self.mark_stopped()
