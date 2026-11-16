import logging

from core.command_completion.models import CompletionCandidate, CompletionContext

logger = logging.getLogger(__name__)


class CommandCompletionRegistry:
    """
    CommandCompletionProvider 注册表。
    """

    def __init__(self, providers: dict | None = None):
        self._providers = {}
        for name, provider in (providers or {}).items():
            self.register(name, provider)

    def register(self, name: str, provider):
        key = str(name or '').strip().lower()
        if not key:
            raise ValueError('completion provider name is required')
        if key in self._providers:
            raise ValueError(f'completion provider already registered: {key}')
        if not callable(getattr(provider, 'complete', None)):
            raise TypeError('completion provider must implement complete')
        self._providers[key] = provider
        return provider

    def get(self, name: str):
        return self._providers.get(str(name or '').strip().lower())

    def complete(self, context: CompletionContext) -> list[CompletionCandidate]:
        result: list[CompletionCandidate] = []
        target = context.resolved_target
        providers = []
        if target is not None:
            selected = self.get(target.completion.provider)
            if selected is not None and getattr(selected, 'provider_key', '') == target.completion.provider:
                providers.append(selected)
        # Non-schema syntaxes (history / !N / help / manifest) remain contextual.
        providers.extend(provider for provider in self._providers.values()
                         if not getattr(provider, 'provider_key', ''))
        for provider in providers:
            try:
                if not provider.supports(context):
                    continue
                result.extend(provider.complete(context))
            except Exception:
                # Provider failures must not block typing, but should be observable.
                logger.exception("Completion provider failed: %s", type(provider).__name__)
                continue

        return self._dedupe(result)

    def _dedupe(self, candidates: list[CompletionCandidate]) -> list[CompletionCandidate]:
        seen = set()
        result = []
        for candidate in candidates:
            key = (candidate.insert_text or candidate.title or '').strip()
            if not key or key in seen:
                continue
            seen.add(key)
            result.append(candidate)
        result.sort(key=lambda item: (item.priority, item.title.lower()))
        return result
