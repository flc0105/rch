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
            'name': 'fusion_wait_seconds',
            'type': 'number',
            'default': 1.5,
            'min': 0.5,
            'max': 5,
            'description': 'Wait briefly before using a banner as fallback when no badge update arrives.',
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
_BANNER_PLACEHOLDERS = {
    'body',
    'title',
    'subtitle',
    'message',
    'notification',
    'notification body',
    'notification title',
    'close',
    'options',
    'show',
}


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


def _row_banner_texts(row: dict) -> list[str]:
    # AXIdentifier values such as literal `body`/`title` are control metadata,
    # not message text. Keep identifiers for diagnostics, but never promote
    # them to user-visible notification content.
    result = []
    for key in ('title', 'description', 'value', 'help'):
        value = _safe_text(row.get(key))
        if value and value not in result:
            result.append(value)
    return result


def _banner_preview(texts: list[str]) -> str:
    for value in reversed(texts):
        cleaned = _safe_text(value)
        lowered = cleaned.casefold()
        if not cleaned:
            continue
        if any(hint == lowered for hint in _WECHAT_NAME_HINTS):
            continue
        if lowered in _BANNER_PLACEHOLDERS:
            continue
        return cleaned
    return ''


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
        self._active_banner_signatures = set()
        self._banners_initialized = False
        self._pending_banner = None
        self._last_badge_emit_at = 0.0

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
            visible_texts = []
            detection_texts = []
            seen_visible = set()
            seen_detection = set()
            for banner_row in banner_rows:
                for value in _row_texts(banner_row):
                    if value and value not in seen_detection:
                        seen_detection.add(value)
                        detection_texts.append(value)
                for value in _row_banner_texts(banner_row):
                    if value and value not in seen_visible:
                        seen_visible.add(value)
                        visible_texts.append(value)
            lowered = ' | '.join(detection_texts).casefold()
            if not any(hint in lowered for hint in _WECHAT_NAME_HINTS):
                continue
            banners.append({
                'texts': visible_texts[:24],
                'signature_texts': detection_texts[:24],
                'subroles': sorted({
                    item.get('subrole') for item in banner_rows
                    if item.get('subrole')
                }),
            })
        return banners

    def _emit_badge_increase(self, old_count, new_count, probe):
        message = f'WeChat unread messages: {new_count}'
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
        self.send_to_server(1, f'Device event emitted: {message}', 0)

    def _queue_banner_fallback(self, banner: dict, fusion_wait_seconds: float):
        now = time.monotonic()
        if now - self._last_badge_emit_at < fusion_wait_seconds:
            self.send_to_server(
                1,
                'WeChat banner suppressed because a badge notification was just emitted',
                0,
            )
            return False

        texts = [str(value) for value in banner.get('texts') or [] if str(value).strip()]
        preview = _banner_preview(texts)
        self._pending_banner = {
            'banner': banner,
            'preview': preview,
            'observed_at': now,
        }
        kind = 'content' if preview else 'generic'
        self.send_to_server(
            1,
            f'WeChat {kind} banner pending badge-priority fallback: wait={fusion_wait_seconds:.2f}s',
            0,
        )
        return True

    def _flush_pending_banner(self, fusion_wait_seconds: float, *, force: bool = False) -> bool:
        pending = self._pending_banner
        if pending is None:
            return False
        age = time.monotonic() - float(pending.get('observed_at') or 0.0)
        if not force and age < fusion_wait_seconds:
            return False

        banner = pending.get('banner') or {}
        preview = _safe_text(pending.get('preview'))
        texts = [str(value) for value in banner.get('texts') or [] if str(value).strip()]
        if preview:
            message = f'WeChat notification received: {preview}'
            content_available = True
        else:
            message = 'WeChat received a new message'
            content_available = False
        events.emit(
            'app.wechat.message_received',
            data={
                'source': 'macos_notification_banner',
                'texts': texts,
                'subroles': banner.get('subroles') or [],
                'content_available': content_available,
            },
            message=message,
        )
        self._pending_banner = None
        self.send_to_server(1, f'Device event emitted: {message}', 0)
        return True

    def _handle_new_banner(self, banner: dict, fusion_wait_seconds: float) -> bool:
        # Badge is the proven, clean macOS signal.  Banners are fallback only:
        # they wait briefly for a badge update and can never delay or cancel it.
        return self._queue_banner_fallback(banner, fusion_wait_seconds)

    def run(self):
        if sys.platform != 'darwin':
            self._report_state('error', status=0, text='WeChat macOS Message Probe is macOS-only')
            self.mark_stopped()
            return

        self.mark_running()
        failed = False
        interval = float(self.get_job_param('interval', 1.0) or 1.0)
        monitor_banners = bool(self.get_job_param('monitor_banners', True))
        fusion_wait_seconds = float(self.get_job_param('fusion_wait_seconds', 1.5) or 1.5)
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
                                # Badge updates are authoritative and immediate.  A
                                # banner may be absent, delayed, malformed, or fail
                                # to probe; none of those conditions may swallow the
                                # already-proven AXTitle unread-count signal.
                                self._emit_badge_increase(old_count, count, probe)
                                self._last_badge_emit_at = time.monotonic()
                                if self._pending_banner is not None:
                                    self.send_to_server(
                                        1,
                                        'Pending WeChat banner fallback cancelled by badge notification',
                                        0,
                                    )
                                    self._pending_banner = None
                            except Exception as exc:
                                self.send_to_server(0, f'Badge Device event emit failed: {exc}', 0)
                else:
                    self._badge_initialized = False
                    self._last_badge_count = None

                if monitor_banners:
                    try:
                        banners = self._banner_probe(workspace, ax)
                        active_signatures = {
                            tuple(banner.get('signature_texts') or banner.get('texts') or [])
                            for banner in banners
                            if tuple(banner.get('signature_texts') or banner.get('texts') or [])
                        }
                        if not self._banners_initialized:
                            self._active_banner_signatures = active_signatures
                            self._banners_initialized = True
                            if debug_ax:
                                self.send_to_server(
                                    1,
                                    f'WeChat banner baseline: active={len(active_signatures)}',
                                    0,
                                )
                        else:
                            for banner in banners:
                                signature = tuple(
                                    banner.get('signature_texts') or banner.get('texts') or []
                                )
                                if signature and signature not in self._active_banner_signatures:
                                    self._handle_new_banner(banner, fusion_wait_seconds)
                            self._active_banner_signatures = active_signatures
                        self._flush_pending_banner(fusion_wait_seconds)
                    except Exception as exc:
                        if debug_ax:
                            self.send_to_server(0, f'Notification banner probe failed: {exc}', 0)
                    # The fallback timer is independent of banner-probe success.
                    # A failed AX scan must never strand a pending notification.
                    try:
                        self._flush_pending_banner(fusion_wait_seconds)
                    except Exception as exc:
                        self.send_to_server(0, f'Banner fallback emit failed: {exc}', 0)

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
