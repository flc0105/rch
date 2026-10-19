import os
import json

from server.config.admin_auth import load_admin_auth

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_DIR = os.path.dirname(BASE_DIR)
BACKEND_DIR = os.path.dirname(SERVER_DIR)

# ------------------ network ------------------ #
SOCKET_HOST = ''
SOCKET_PORT = int(os.getenv('RCH_SOCKET_PORT', '9999'))
SOCKET_ADDR = (SOCKET_HOST, SOCKET_PORT)

WEB_HOST = '0.0.0.0'
WEB_PORT = int(os.getenv('RCH_WEB_PORT', '8085'))
WEB_FILE_TRANSFER_PORT = WEB_PORT + 1
if not (1 <= SOCKET_PORT <= 65535 and 1 <= WEB_PORT <= 65534) or SOCKET_PORT in (WEB_PORT, WEB_FILE_TRANSFER_PORT):
    raise ValueError('Invalid or overlapping RCH socket/web/file ports')

# ------------------ auth ------------------ #
HIDDEN_DEVICES_REQUIRE_PASSWORD = os.getenv('RCH_HIDDEN_DEVICES_REQUIRE_PASSWORD', 'true').strip().lower() in {
    '1', 'true', 'yes', 'on',
}
HIDDEN_DEVICES_PASSWORD = os.getenv('RCH_HIDDEN_DEVICES_PASSWORD', '1')
WEB_AUTH_SESSION_DAYS = int(os.getenv('RCH_WEB_AUTH_SESSION_DAYS', '7'))
SESSION_COOKIE_NAME = os.getenv('RCH_WEB_SESSION_COOKIE_NAME', 'rch_admin_session')

# ------------------resources ------------------ #
ALIAS_PATH = os.path.join(SERVER_DIR, 'resources/aliases.json')
SCRIPT_PATH = os.path.join(SERVER_DIR, 'resources/scripts')
SCRIPT_JOBS_PATH = os.path.join(SERVER_DIR, 'resources/jobs')

EXTERNAL_TOOLS_ROOT = os.path.join(SERVER_DIR, 'resources/external_tools')
EXTERNAL_TOOL_META_PATH = os.path.join(EXTERNAL_TOOLS_ROOT, 'metas')
EXTERNAL_TOOL_PACKAGE_PATH = os.path.join(EXTERNAL_TOOLS_ROOT, 'packages')

# ------------------ runtime ------------------ #
# Override with RCH_SERVER_RUNTIME_DIR (absolute, or relative to backend/).
# Default is always <project>/backend/runtime, independent of the launch CWD.
SERVER_RUNTIME_DIR = os.path.abspath(os.path.join(
    BACKEND_DIR,
    os.path.expanduser(os.environ.get('RCH_SERVER_RUNTIME_DIR', '').strip() or 'runtime'),
))
os.makedirs(SERVER_RUNTIME_DIR, exist_ok=True)
_AUTH = load_admin_auth(os.path.join(SERVER_RUNTIME_DIR, 'auth.json'))
ADMIN_USERNAME = _AUTH['username']
ADMIN_PASSWORD_HASH = _AUTH['password']
ADMIN_API_TOKEN = _AUTH['api_token']
WEB_SESSION_SECRET = _AUTH['session_secret']

# ------------------ cleanup ------------------ #
SERVER_CLEANUP_START_DELAY_SECONDS = 20
SERVER_CLEANUP_LOG_ROOT_DIR = os.path.join(SERVER_RUNTIME_DIR, 'cleanup_logs')
SERVER_CLEANUP_ITEMS = (
    'notifications',
    'agent_build_temp',
    'agent_transient_outputs',
    'preview_cache',
    'upload_tmp',
    'cleanup_logs',
)

# ------------------ history ------------------ #
RCH_DB_PATH = os.path.join(SERVER_RUNTIME_DIR, 'rch.db')
COMMAND_HISTORY_RECENT_LIMIT = 100
COMMAND_HISTORY_PAGE_SIZE = 50
COMMAND_HISTORY_MAX_PAGE_SIZE = 200
COMMAND_HISTORY_MAX_OUTPUT_RECORD_CHARS = 64 * 1024
COMMAND_HISTORY_MAX_OUTPUT_SUMMARY_CHARS = 512
COMMAND_HISTORY_MAX_OUTPUT_RECORDS = 256
# Execution history 不做条数 / 时间裁剪。
# Quick History 仅保留最近 100 个 unique command；Pinned 独立永久保存。
# 单条 execution 最多保存 64KiB 输出文本和 256 段记录，避免极碎 chunk 的 metadata 膨胀。
KEYCHAINS_ROOT_DIR = os.path.join(SERVER_RUNTIME_DIR, 'keychains')

# ------------------ web files ------------------ #
WEB_FILES_ROOT_DIR = os.path.join(SERVER_RUNTIME_DIR, 'web_files')
WEB_PREVIEW_TEXT_MAX_BYTES = 512 * 1024

# Server-local Documents: JSON mapping of root IDs to absolute paths or {label, path}.
# Defaults expose bundled RCH docs and a persistent Notes directory.
_DEFAULT_DOCUMENT_ROOTS = {
    'rch': {'label': 'RCH Docs', 'path': os.path.join(BACKEND_DIR, 'docs')},
    'notes': {'label': 'Notes', 'path': os.path.join(SERVER_RUNTIME_DIR, 'documents', 'notes')},
}
if 'RCH_DOCUMENT_ROOTS' in os.environ:
    DOCUMENT_ROOTS = json.loads(os.environ['RCH_DOCUMENT_ROOTS'])
else:
    os.makedirs(_DEFAULT_DOCUMENT_ROOTS['notes']['path'], exist_ok=True)
    DOCUMENT_ROOTS = _DEFAULT_DOCUMENT_ROOTS
WEB_HTTP_UPLOAD_MAX_BYTES = 10 * 1024 * 1024 * 1024  # 10GB
WEB_PUBLIC_BASE_URL = f'http://127.0.0.1:{WEB_PORT}'

HEARTBEAT_INTERVAL_SECONDS = 30
