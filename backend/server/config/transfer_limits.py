"""Server HTTP intake and in-flight staging limits."""
import os

WEB_HTTP_UPLOAD_MAX_BYTES = 10 * 1024 * 1024 * 1024  # 10 GiB
# Shared request bodies and dedicated upload_tmp reservations share this process budget.
WEB_UPLOAD_STAGING_MAX_BYTES = int(os.getenv('RCH_WEB_UPLOAD_STAGING_MAX_BYTES', str(2 * WEB_HTTP_UPLOAD_MAX_BYTES)))
WEB_UPLOAD_STAGING_MAX_SLOTS = int(os.getenv('RCH_WEB_UPLOAD_STAGING_MAX_SLOTS', '12'))
WEB_UPLOAD_STAGING_MAX_DEVICE_SLOTS = int(os.getenv('RCH_WEB_UPLOAD_STAGING_MAX_DEVICE_SLOTS', '4'))
