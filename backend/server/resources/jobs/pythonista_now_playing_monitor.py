JOB_METADATA = {
    "name": "pythonista_now_playing_monitor",
    "display_name": "Pythonista Now Playing Monitor",
    "description": "Monitor current playing music in Pythonista and send only when track changes",
    "platforms": ["ios"],
    "params": [
        {
            "name": "interval_seconds",
            "type": "integer",
            "required": False,
            "default": 3,
            "min": 1,
            "description": "Polling interval in seconds"
        }
    ]
}

import threading
import time
from ctypes import c_void_p

from client.jobs.job import Job
from core.utils.logger import logger


class PythonistaNowPlayingMonitor(Job):
    def __init__(self):
        super().__init__()
        self.interval = 3
        self.last_track_key = None
        self.last_has_item = None

    def on_context_bound(self):
        self.interval = int(self.get_job_param('interval_seconds', 3) or 3)

    def run(self):
        try:
            time.sleep(2)

            from objc_util import ObjCClass, ObjCInstance, load_framework, c, sel
            load_framework('MediaPlayer')

            self.send_to_server(1, 'Dependency loaded: objc_util / MediaPlayer', 0)

            MPMusicPlayerController = ObjCClass('MPMusicPlayerController')

            def msg_obj_0(obj, selector_name):
                c.objc_msgSend.restype = c_void_p
                c.objc_msgSend.argtypes = [c_void_p, c_void_p]
                p = c.objc_msgSend(obj.ptr, sel(selector_name))
                return ObjCInstance(p) if p else None

            def get_now_playing_info():
                player = MPMusicPlayerController.systemMusicPlayer()
                item = player.nowPlayingItem()

                if not item:
                    return {
                        'has_item': False,
                        'title': None,
                        'artist': None,
                        'album': None,
                    }

                title_obj = msg_obj_0(item, 'title')
                artist_obj = msg_obj_0(item, 'artist')
                album_obj = msg_obj_0(item, 'albumTitle')

                title = str(title_obj) if title_obj else None
                artist = str(artist_obj) if artist_obj else None
                album = str(album_obj) if album_obj else None

                return {
                    'has_item': True,
                    'title': title,
                    'artist': artist,
                    'album': album,
                }

            self.mark_running()
            self.send_to_server(1, 'Pythonista now playing monitor started', 0)

            while not self.stop_event.is_set():
                try:
                    info = get_now_playing_info()
                    has_item = info['has_item']
                    track_key = None

                    if has_item:
                        track_key = (
                            info['title'] or '',
                            info['artist'] or '',
                            info['album'] or '',
                        )

                    changed = False

                    if self.last_has_item is None:
                        changed = True
                    elif has_item != self.last_has_item:
                        changed = True
                    elif has_item and track_key != self.last_track_key:
                        changed = True

                    if changed:
                        self.last_has_item = has_item
                        self.last_track_key = track_key

                        if has_item:
                            self.send_to_server(
                                1,
                                f"Now playing changed: title={info['title'] or ''}, artist={info['artist'] or ''}, album={info['album'] or ''}",
                                0
                            )
                        else:
                            self.send_to_server(1, 'Now playing cleared', 0)

                except Exception as e:
                    self.send_to_server(0, f'Now playing polling error: {e}', 0)

                time.sleep(self.interval)

            self.send_to_server(1, 'Pythonista now playing monitor stopped', 0)

        except Exception as e:
            self.send_to_server(0, f'Pythonista now playing monitor error: {e}', 0)
        finally:
            self.mark_stopped()
            logger.info(f'Thread ended: {threading.current_thread().name}')
            self.send_to_server(1, f'Task ended: {threading.current_thread().name}', 1)

    def stop(self, notify: bool = True):
        self.request_stop(notify=notify)