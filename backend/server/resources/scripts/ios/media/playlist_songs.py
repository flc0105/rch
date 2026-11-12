SCRIPT_METADATA = {
    "name": "ios/media/playlist_songs",
    "display_name": "Playlist Songs",
    "description": "Browse songs from a playlist in your iOS music library.",
    "platforms": ["ios"],
    "category": "Media",
    "params": [
        {
            "name": "playlist_name",
            "label": "Playlist",
            "type": "string",
            "required": False,
            "default": "",
            "description": "Leave blank to browse your favorite songs."
        }
    ]
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
        return getattr(obj, selector_name)()
    except Exception:
        return default


def media_prop(obj, prop_name, default=None):
    try:
        value = obj.valueForProperty_(ns(prop_name))
        return default if value is None else value
    except Exception:
        return default


def nsdate_to_iso(d):
    if d is None:
        return ''
    try:
        ts = float(d.timeIntervalSince1970())
        return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        return ''


def duration_mmss(value):
    try:
        seconds = max(0, int(round(float(value or 0))))
    except (ValueError, TypeError, OverflowError):
        seconds = 0
    return '{:02d}:{:02d}'.format(seconds // 60, seconds % 60)


def iter_nsarray(arr):
    if arr is None:
        return
    count = int(arr.count())
    for i in range(count):
        yield arr.objectAtIndex_(i)


def normalize_name(s):
    return ''.join(str(s).casefold().split())


def playlist_name(pl):
    name = safe_call(pl, 'name', '')
    if not name:
        name = media_prop(pl, 'name', '')
    return ns_to_py(name)


def playlist_items(pl):
    try:
        return pl.items()
    except Exception:
        return None


def is_default_favorites_name(name):
    candidates = (
        '喜爱歌曲',       # 实测名称
        '喜爱的歌曲',     # 简体中文 Apple 文档
        '喜好歌曲',       # 繁体中文 Apple 文档
        'Favorite Songs', # 英文 Apple 文档
    )
    return normalize_name(name) in {normalize_name(c) for c in candidates}


def find_playlist(target_name):
    query = MPMediaQuery.playlistsQuery()
    collections = query.collections()
    if collections is None:
        return None

    target_norm = normalize_name(target_name)
    favorite_matches = []

    for pl in iter_nsarray(collections):
        name = playlist_name(pl)
        if target_norm:
            if normalize_name(name) == target_norm:
                return pl
        elif is_default_favorites_name(name):
            favorite_matches.append(pl)

    if favorite_matches:
        favorite_matches.sort(
            key=lambda p: int(playlist_items(p).count()) if playlist_items(p) is not None else 0,
            reverse=True
        )
        return favorite_matches[0]

    return None


def get_persistent_id(item):
    value = safe_call(item, 'persistentID', None)
    if value is None:
        value = media_prop(item, 'persistentID', None)
    return ns_to_py(value)


def date_property(item, selector, key):
    value = safe_call(item, selector, None)
    if value is None:
        value = media_prop(item, key, None)
    return value


def release_year(date):
    if date is None:
        return None
    try:
        ts = float(date.timeIntervalSince1970())
        return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).year
    except Exception:
        return None


def song_row(item):
    date_added = media_prop(item, 'dateAdded', None)
    last_played = date_property(item, 'lastPlayedDate', 'lastPlayedDate')
    release_date = date_property(item, 'releaseDate', 'releaseDate')

    return {
        'persistentID': get_persistent_id(item),
        'artist': ns_to_py(safe_call(item, 'artist', '')),
        'title': ns_to_py(safe_call(item, 'title', '')),
        'album': ns_to_py(safe_call(item, 'albumTitle', '')),
        'albumArtist': ns_to_py(safe_call(item, 'albumArtist', '')),
        'genre': ns_to_py(safe_call(item, 'genre', '')),
        'composer': ns_to_py(safe_call(item, 'composer', '')),
        'playCount': num_to_int(safe_call(item, 'playCount', 0), 0),
        'skipCount': num_to_int(safe_call(item, 'skipCount', 0), 0),
        'dateAdded': nsdate_to_iso(date_added),
        'lastPlayedDate': nsdate_to_iso(last_played),
        'year': release_year(release_date),
        'duration': duration_mmss(safe_call(item, 'playbackDuration', 0)),
    }


def export_playlist_songs(pl):
    items = playlist_items(pl)
    if items is None:
        return []
    return [song_row(item) for item in iter_nsarray(items)]


def main():
    status = request_media_library_access()
    if status in (1, 2):
        print(json.dumps([], ensure_ascii=False, indent=2))
        return

    target_name = str(kwargs.get('playlist_name', '') or '').strip()
    pl = find_playlist(target_name)
    rows = export_playlist_songs(pl) if pl is not None else []
    print(json.dumps(rows, ensure_ascii=False, indent=2))


main()