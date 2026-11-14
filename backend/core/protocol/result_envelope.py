"""Canonical result envelope shared by Control domains and terminal rendering.

Business domains decide status, message, data and intended shape. The wire
result retains those facts; terminal text and JSON are just projections.
"""
from dataclasses import dataclass
from typing import Any

from core.utils.command_output import ResultDataShape, ResultDisplay, ResultEventType


@dataclass(frozen=True)
class ResultEnvelope:
    status: str = 'success'
    message: str = ''
    data: Any = None
    display: ResultDisplay = ResultDisplay.MESSAGE
    shape: ResultDataShape | None = None

    def as_payload(self) -> dict:
        if self.status not in ('success', 'error') or not isinstance(self.message, str):
            raise ValueError('Invalid result status or message')
        if self.display not in (ResultDisplay.MESSAGE, ResultDisplay.DATA):
            raise ValueError('Invalid result display')
        payload = {'event_type': ResultEventType.COMPLETED,
                   'status': self.status, 'display': self.display, 'message': self.message}
        if self.data is not None:
            if not isinstance(self.data, (dict, list)):
                raise ValueError('Result data must be an object or array')
            payload['data'] = self.data
        if self.display == ResultDisplay.DATA and self.status == 'success':
            if self.data is None:
                raise ValueError('Successful data result requires data')
            shape = self.shape or (ResultDataShape.TABLE if isinstance(self.data, list)
                                   else ResultDataShape.FLAT)
            if (shape == ResultDataShape.TABLE) != isinstance(self.data, list):
                raise ValueError('Result shape does not match data')
            payload['shape'] = shape
        return payload
