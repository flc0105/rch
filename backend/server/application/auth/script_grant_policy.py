import re


class ScriptGrantPolicy:
    """
    Script Grant 路由策略。

    职责：
    - 维护 scope 与 HTTP method/path 的映射
    - 判断一次 Web API 请求需要哪个 scope

    注意：
    - 这里只做 API URL 级别授权
    - 不处理 artifact type / artifact_id 等资源级判断
    """

    ROUTE_RULES = [
        {'scope': 'scripts:read', 'method': 'GET', 'path': '/api/scripts/download'},
        {'scope': 'interactions:request', 'method': 'POST', 'path': '/api/interactions/client/request'},
        {'scope': 'artifacts:list', 'method': 'GET', 'path': '/api/artifacts'},
        {'scope': 'artifacts:download', 'method': 'GET', 'path': '/api/artifacts/<artifact_id>/download'},
        {'scope': 'artifacts:raw', 'method': 'GET', 'path': '/api/artifacts/<artifact_id>/raw'},
        {'scope': 'artifacts:preview', 'method': 'GET', 'path': '/api/artifacts/<artifact_id>/preview'},
        {'scope': 'keychains:list', 'method': 'GET', 'path': '/api/keychains'},
        {'scope': 'keychains:resolve', 'method': 'POST', 'path': '/api/keychains/resolve'},
        {'scope': 'keychains:create', 'method': 'POST', 'path': '/api/keychains'},
        {'scope': 'external_tools:catalog', 'method': 'GET', 'path': '/api/external-tools/catalog'},
        {'scope': 'workspace:read', 'method': 'GET', 'path': '/api/connections/<client_id>/pinned_paths'},
    ]

    def __init__(self, rules=None):
        self.rules = []
        for item in rules or self.ROUTE_RULES:
            normalized = self._normalize_rule(item)
            if normalized:
                self.rules.append(normalized)
        self.supported_scopes = {item['scope'] for item in self.rules}

    def _safe_text(self, value) -> str:
        return str(value or '').strip()

    def _normalize_rule(self, item) -> dict | None:
        if not isinstance(item, dict):
            return None

        scope = self._safe_text(item.get('scope'))
        method = self._safe_text(item.get('method')).upper()
        path = self._safe_text(item.get('path'))
        if not scope or not method or not path:
            return None

        return {
            'scope': scope,
            'method': method,
            'path': path,
            'regex': self._compile_path_template(path),
        }

    def _compile_path_template(self, path_template: str):
        pieces = []
        cursor = 0
        for match in re.finditer(r'<[^/>]+>', path_template):
            pieces.append(re.escape(path_template[cursor:match.start()]))
            pieces.append(r'[^/]+')
            cursor = match.end()
        pieces.append(re.escape(path_template[cursor:]))
        pattern = ''.join(pieces)
        return re.compile(f'^{pattern}$')

    def is_supported_scope(self, scope: str) -> bool:
        return self._safe_text(scope) in self.supported_scopes

    def match_request_scope(self, method: str, path: str) -> str:
        normalized_method = self._safe_text(method).upper()
        normalized_path = self._safe_text(path)
        if not normalized_method or not normalized_path:
            return ''

        for item in self.rules:
            if item.get('method') != normalized_method:
                continue
            if item.get('regex').match(normalized_path):
                return item.get('scope', '')
        return ''
