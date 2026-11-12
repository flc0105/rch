SCRIPT_METADATA = {
    "name": "ios/media/music_library",
    "display_name": "Music Library Songs",
    "description": "Browse the songs in your iOS music library.",
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


def media_prop(item, prop_name, default=None):
    try:
        v = item.valueForProperty_(ns(prop_name))
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


def get_persistent_id(item):
    """
    Return the song item's media-library ID. It may change after an unsync/resync.
    """
    v = safe_call(item, 'persistentID', None)
    if v is None:
        v = media_prop(item, 'persistentID', None)
    return ns_to_py(v)


def song_rows():
    query = MPMediaQuery.songsQuery()
    items = query.items()
    if items is None:
        return []

    rows = []
    for item in iter_nsarray(items):
        date_added = media_prop(item, 'dateAdded', None)
        pid = get_persistent_id(item)

        rows.append({
            'persistentID': pid,
            'artist': ns_to_py(safe_call(item, 'artist', '')),
            'title': ns_to_py(safe_call(item, 'title', '')),
            'album': ns_to_py(safe_call(item, 'albumTitle', '')),
            'playCount': num_to_int(safe_call(item, 'playCount', 0), 0),
            'dateAdded': nsdate_to_iso(date_added),
        })

    rows.sort(
        key=lambda r: (
            r['artist'].casefold(),
            r['title'].casefold(),
            r['album'].casefold(),
        )
    )
    return rows


def main():
    status = request_media_library_access()
    if status in (1, 2):
        print(json.dumps([], ensure_ascii=False, indent=2))
        return

    rows = song_rows()

    print(json.dumps(rows, ensure_ascii=False, indent=2))


main()