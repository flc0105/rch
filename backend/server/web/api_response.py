import traceback

from flask import jsonify
from werkzeug.exceptions import ClientDisconnected, RequestEntityTooLarge

from core.utils.logger import logger


class WebApiResponder:
    def ok(self, data=None, message='ok', code=0, http_status=200):
        payload = {
            'code': code,
            'message': message,
        }
        if data is not None:
            payload['data'] = data
        return jsonify(payload), http_status

    def fail(self, message, http_status=400, code=1, **extra):
        payload = {
            'code': code,
            'message': str(message),
        }
        if extra:
            payload.update(extra)
        return jsonify(payload), http_status

    def map_common_error(self, error):
        if isinstance(error, ValueError):
            return self.fail(str(error), 400)
        if isinstance(error, FileNotFoundError):
            return self.fail('file not found', 404)
        if isinstance(error, PermissionError):
            return self.fail('Forbidden', 403)
        return self.fail(str(error), 500)

    def json_endpoint(self, func, *, default_error_status=400):
        try:
            return self.ok(func())
        except RequestEntityTooLarge:
            return self.fail('File is too large', 413)
        except ClientDisconnected:
            return self.fail('Client disconnected during upload', 400)
        except ValueError as e:
            return self.fail(e, 400)
        except FileNotFoundError as e:
            return self.fail(e, 404)
        except PermissionError:
            return self.fail('Forbidden', 403)
        except Exception as e:
            logger.error(f'Web API error: {e}', exc_info=True)
            traceback.print_exc()

            # Web 端不要直接暴露 CLI/底层选择错误文案
            message = str(e)
            http_status = default_error_status
            if message == 'Not a valid selection':
                message = 'Client is offline or not found'
                http_status = 404

            return self.fail(message, http_status)

    def file_endpoint(self, func):
        try:
            return self.ok(func())
        except Exception as e:
            return self.map_common_error(e)


__all__ = ['WebApiResponder']
