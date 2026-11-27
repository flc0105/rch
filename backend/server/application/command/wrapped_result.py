"""Consume nested command events without inferring an outcome from output."""
from core.protocol.result_envelope import ResultEvent, ResultStreamState


def iter_inner_results(items):
    state = ResultStreamState()
    for item in items:
        state.accept(item)
        if item.terminal_status is None:
            yield item
    yield state.completion or ResultEvent.completed('interrupted', 'Result stream ended without completed event')
