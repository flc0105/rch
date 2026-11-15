from core.utils.logger import logger


class ServerResultDispatcher:
    """Route canonical Result events to their waiting request."""

    def __init__(self, session):
        self.session = session

    def dispatch_result(self, command_id, event, before_enqueue=None):
        if self.session.runtime.pending_results.deliver(command_id, event, before_enqueue):
            return True
        # Never deliver a late / duplicate result to a different request.
        if command_id is not None and command_id != 0:
            return False
        if before_enqueue is not None:
            before_enqueue()
        self._handle_unexpected_message(event)
        return True

    def _handle_unexpected_message(self, event):
        # The unsolicited-message callback and queue are display-oriented.
        # The original event remains canonical up to this presentation boundary.
        status = 1 if event.get('event_type') != 'completed' or event.get('status') in ('success', 'partial') else 0
        text = event.get('message') or ''
        if not text and 'data' in event:
            import json
            text = json.dumps(event['data'], ensure_ascii=False)
        end = event.get('event_type') == 'completed'
        callback = self.session.context.on_unexpected_message
        if callable(callback):
            try:
                callback(status, text, end)
                return
            except Exception:
                pass
        if self.session.context.is_interactive:
            logger.info(text)
            return
        self.session.runtime.message_queue.put(status, text, end)
