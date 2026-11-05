"""Client Session Token API allowlist.

Add a (HTTP method, route template) pair here when a connected Client needs a
new Server API. Unlisted routes, including command dispatch and Admin APIs,
remain unavailable to Client Session Tokens. No per-script or per-command grants.
"""
import re


class ClientApiPolicy:
    # Only these endpoints accept X-Client-Session-Token.
    ROUTES = (
        # Client scripts and SDK
        ('GET', '/api/scripts/download'),
        ('GET', '/api/jobs/list'),
        ('GET', '/api/jobs/download'),
        ('POST', '/api/background-jobs/report'),
        ('POST', '/api/device-events'),
        ('POST', '/api/agent/build'),
        ('GET', '/api/agent/download/<filename>'),
        ('GET', '/api/external-tools/catalog'),
        ('GET', '/api/connections/<client_id>/pinned_paths'),
        # Artifacts
        ('GET', '/api/artifacts'),
        ('GET', '/api/artifacts/<artifact_id>/download'),
        ('GET', '/api/artifacts/<artifact_id>/raw'),
        ('GET', '/api/artifacts/<artifact_id>/preview'),
        # Connected Client's machine Keychains and Server Shared Keychains.
        # Machine ownership is checked in the Keychain API, not by a URL string.
        ('GET', '/api/keychains'),
        ('GET', '/api/keychains/<cred_id>'),
        ('POST', '/api/keychains'),
        ('POST', '/api/keychains/resolve'),
        ('PUT', '/api/keychains/<cred_id>'),
        ('DELETE', '/api/keychains/<cred_id>'),
        # Browser-based interaction tied to a running Client command.
        ('POST', '/api/interactions/client/request'),
    )

    def __init__(self, routes=None):
        self.routes = tuple(routes) if routes is not None else self.ROUTES
        self._patterns = tuple(
            (method, self._compile(path)) for method, path in self.routes
        )

    @staticmethod
    def _compile(path):
        fragments = []
        cursor = 0
        for match in re.finditer(r'<[^/>]+>', path):
            fragments.append(re.escape(path[cursor:match.start()]))
            fragments.append(r'[^/]+')
            cursor = match.end()
        fragments.append(re.escape(path[cursor:]))
        return re.compile(r'^' + ''.join(fragments) + r'$')

    def allows(self, method, path):
        normalized_method = str(method or '').upper()
        normalized_path = str(path or '')
        return any(m == normalized_method and pattern.fullmatch(normalized_path)
                   for m, pattern in self._patterns)
