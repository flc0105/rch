SCRIPT_METADATA = {
    "name": "ios/media/music_playlists",
    "display_name": "Playlists",
    "description": "Browse the playlists in your iOS music library.",
    "platforms": ["ios"],
    "category": "Media",
    "params": []
}

import ctypes
import json
import time
import datetime

from objc_util import NSBundle, ObjCClass, ObjCBlock, ns

NSBundle.bundleWithPath_('/System/Library/Frameworks/MediaPlayer.framework').load()

MPMediaLibrary = ObjCClass('MPMediaLibrary')
MPMediaQuery = ObjCClass('MPMediaQuery')

_auth_done = False
_auth_status = None
_auth_block = None


def request_media_library_access(timeout=15):
    global _auth_done, _auth_status, _auth_block

    try:
        status = MPMediaLibrary.authorizationStatus()
    except Exception:
        return None

    # 0 = notDetermined
    # 1 = restricted
    # 2 = denied
    # 3 = authorized
    if status != 0:
        return int(status)

    def handler(status_value):
        global _auth_done, _auth_status
        _auth_status = int(status_value)
        _auth_done = True

    _auth_done = False
    _auth_status = None
    _auth_block = ObjCBlock(
        handler,
        restype=None,
        argtypes=[ctypes.c_long]
    )

    MPMediaLibrary.requestAuthorization_(_auth_block)

    start = time.time()
    while not _auth_done and (time.time() - start) < timeout:
        time.sleep(0.1)

    return _auth_status


def ns_to_py(x):
    if x is None:
        return ''
    try:
        return str(x)
    except Exception:
        return ''


def num_to_int(x, default=0):
    if x is None:
        return default
    try:
        return int(x)
    except Exception:
        try:
            return int(str(x))
        except Exception:
            return default


def safe_call(obj, selector_name, default=None):
    try:
        fn = getattr(obj, selector_name)
        return fn()
    except Exception:
        return default


def media_prop(obj, prop_name, default=None):
    try:
        v = obj.valueForProperty_(ns(prop_name))
        if v is None:
            return default
        return v
    except Exception:
        return default


def nsdate_to_iso(d):
    if d is None:
        return ''
    try:
        ts = float(d.timeIntervalSince1970())
        return datetime.datetime.utcfromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        return ''


def iter_nsarray(arr):
    if arr is None:
        return
    count = int(arr.count())
    for i in range(count):
        yield arr.objectAtIndex_(i)


def playlist_name(pl):
    name = safe_call(pl, 'name', '')
    if not name:
        name = media_prop(pl, 'name', '')
    return ns_to_py(name)


def playlist_persistent_id(pl):
    v = safe_call(pl, 'persistentID', None)
    if v is None:
        v = media_prop(pl, 'persistentID', None)
    return ns_to_py(v)


def playlist_items(pl):
    try:
        return pl.items()
    except Exception:
        return None


def list_playlists():
    query = MPMediaQuery.playlistsQuery()
    collections = query.collections()

    rows = []

    if collections is None:
        return rows

    for pl in iter_nsarray(collections):
        items = playlist_items(pl)
        count = int(items.count()) if items is not None else 0

        rows.append({
            'name': playlist_name(pl),
            'persistentID': playlist_persistent_id(pl),
            'count': count,
        })

    rows.sort(
        key=lambda r: (
            r['name'].casefold(),
            r['persistentID']
        )
    )

    return rows


def main():
    status = request_media_library_access()
    if status in (1, 2):
        print('没有媒体库权限。请在 iOS 设置中允许 Pythonista 访问媒体与 Apple Music。')
        return

    rows = list_playlists()

    print(json.dumps(rows, ensure_ascii=False, indent=2))


main()