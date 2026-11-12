SCRIPT_METADATA = {
    "name": "ios/recon/playlist_songs",
    "display_name": "Playlist Songs",
    "description": "Export songs from a specified playlist in the iOS music library",
    "platforms": ["ios"],
    "category": "Recon",
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


# =========================
# 直接在这里写死 playlist 名称
# 留空则默认找 Favorite Songs / 喜爱的歌曲 / 收藏的歌曲
# =========================
PLAYLIST_NAME = 'My Playlist'


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


def normalize_name(s):
    return ''.join(str(s).lower().split())


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


def is_default_favorites_name(name):
    n = normalize_name(name)

    candidates = [
        'favoritesongs',
        'favorites',
        'favouritesongs',
        'favourites',
        '喜爱的歌曲',
        '喜愛的歌曲',
        '最喜爱的歌曲',
        '最喜愛的歌曲',
        '收藏的歌曲',
        '我喜爱的歌曲',
        '我喜愛的歌曲',
    ]

    return any(normalize_name(c) == n for c in candidates)


def find_playlist():
    query = MPMediaQuery.playlistsQuery()
    collections = query.collections()

    if collections is None:
        return None, []

    all_playlists = []

    target_name = str(PLAYLIST_NAME).strip()
    target_norm = normalize_name(target_name)

    exact_matches = []
    favorite_matches = []

    for pl in iter_nsarray(collections):
        name = playlist_name(pl)
        items = playlist_items(pl)
        count = int(items.count()) if items is not None else 0

        row = {
            'name': name,
            'persistentID': playlist_persistent_id(pl),
            'count': count,
        }
        all_playlists.append(row)

        if target_name:
            if normalize_name(name) == target_norm:
                exact_matches.append(pl)
        else:
            if is_default_favorites_name(name):
                favorite_matches.append(pl)

    if target_name:
        if exact_matches:
            return exact_matches[0], all_playlists
        return None, all_playlists

    # PLAYLIST_NAME 为空时,默认找 favorites。
    # 如果有多个候选,优先选择歌多的那个。
    if favorite_matches:
        favorite_matches.sort(
            key=lambda p: int(playlist_items(p).count()) if playlist_items(p) is not None else 0,
            reverse=True
        )
        return favorite_matches[0], all_playlists

    return None, all_playlists


def get_persistent_id(item):
    v = safe_call(item, 'persistentID', None)
    if v is None:
        v = media_prop(item, 'persistentID', None)
    return ns_to_py(v)


def song_row(item, index):
    date_added = media_prop(item, 'dateAdded', None)
    rating = media_prop(item, 'rating', 0)

    return {
        'index': index,
        'persistentID': get_persistent_id(item),
        'artist': ns_to_py(safe_call(item, 'artist', '')),
        'title': ns_to_py(safe_call(item, 'title', '')),
        'album': ns_to_py(safe_call(item, 'albumTitle', '')),
        'albumArtist': ns_to_py(safe_call(item, 'albumArtist', '')),
        'genre': ns_to_py(safe_call(item, 'genre', '')),
        'composer': ns_to_py(safe_call(item, 'composer', '')),
        'playCount': num_to_int(safe_call(item, 'playCount', 0), 0),
        'skipCount': num_to_int(safe_call(item, 'skipCount', 0), 0),
        'rating': num_to_int(rating, 0),
        'dateAdded': nsdate_to_iso(date_added),
        'durationSeconds': float(safe_call(item, 'playbackDuration', 0) or 0),
    }


def export_playlist_songs(pl):
    items = playlist_items(pl)
    rows = []

    if items is None:
        return rows

    for index, item in enumerate(iter_nsarray(items)):
        rows.append(song_row(item, index))

    return rows


def main():
    status = request_media_library_access()
    if status in (1, 2):
        print(json.dumps([], ensure_ascii=False, indent=2))
        return

    pl, all_playlists = find_playlist()

    if pl is None:
        print(json.dumps([], ensure_ascii=False, indent=2))
        return

    rows = export_playlist_songs(pl)

    print(json.dumps(rows, ensure_ascii=False, indent=2))


main()