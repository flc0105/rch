import json
from dataclasses import dataclass
from typing import Iterable, Iterator, List, Optional

import requests


class SseAuthenticationError(RuntimeError):
    pass


@dataclass(frozen=True)
class SseEvent:
    event: str
    data: str
    event_id: str = ''

    def json(self):
        return json.loads(self.data or '{}')


def parse_sse_lines(lines: Iterable[str]) -> Iterator[SseEvent]:
    event_type = 'message'
    event_id = ''
    data_lines: List[str] = []

    for raw_line in lines:
        if raw_line is None:
            continue
        line = raw_line.decode('utf-8', errors='replace') if isinstance(raw_line, bytes) else str(raw_line)
        line = line.rstrip('\r\n')

        if line == '':
            if data_lines:
                yield SseEvent(event=event_type or 'message', data='\n'.join(data_lines), event_id=event_id)
            event_type = 'message'
            event_id = ''
            data_lines = []
            continue

        if line.startswith(':'):
            continue

        if ':' in line:
            field, value = line.split(':', 1)
            if value.startswith(' '):
                value = value[1:]
        else:
            field, value = line, ''

        if field == 'event':
            event_type = value or 'message'
        elif field == 'id':
            event_id = value
        elif field == 'data':
            data_lines.append(value)
        # retry is deliberately ignored; reconnect policy is local config.

    if data_lines:
        yield SseEvent(event=event_type or 'message', data='\n'.join(data_lines), event_id=event_id)


class NotificationSseClient:
    def __init__(self, *, url: str, token: str, session: Optional[requests.Session] = None):
        self.url = str(url or '').strip()
        self.token = str(token or '').strip()
        self.session = session or requests.Session()

    def events(self, last_event_id: str = '') -> Iterator[SseEvent]:
        headers = {
            'Accept': 'text/event-stream',
            'Cache-Control': 'no-cache',
            'Authorization': f'Bearer {self.token}',
        }
        normalized_last_id = str(last_event_id or '').strip()
        if normalized_last_id:
            headers['Last-Event-ID'] = normalized_last_id

        with self.session.get(
            self.url,
            headers=headers,
            stream=True,
            timeout=(10, 70),
        ) as response:
            if response.status_code == 401:
                raise SseAuthenticationError('RCH Server rejected the notifier token')
            response.raise_for_status()
            content_type = str(response.headers.get('Content-Type') or '').lower()
            if 'text/event-stream' not in content_type:
                raise RuntimeError(f'Unexpected SSE content type: {content_type or "<missing>"}')

            yield from parse_sse_lines(response.iter_lines(chunk_size=1, decode_unicode=True))
