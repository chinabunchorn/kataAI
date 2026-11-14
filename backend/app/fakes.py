"""Deterministic test adapters; these never evaluate generated code."""

from copy import deepcopy
from typing import Any

from app.proposals import PythonProposal


class FakeModel:
    def __init__(self, proposals: list[dict[str, Any]]) -> None:
        self._proposals = deepcopy(proposals)

    def generate(self, question: str, columns: tuple[str, ...]) -> list[dict[str, Any]]:
        return deepcopy(self._proposals)


class ExecutionUnavailable(Exception):
    def __init__(self) -> None:
        super().__init__('EXECUTION_UNAVAILABLE')


class FakeExecutor:
    def __init__(self, outcome: dict[str, Any], *, available: bool = True) -> None:
        self._outcome = deepcopy(outcome)
        self._available = available

    def execute_handoff(self, request):
        """Accept a validated fake-only handoff; no code or dataset is read."""
        from app.executor_contract import ExecutorRequest
        if type(request) is not ExecutorRequest:
            raise ValueError('INVALID_EXECUTOR_REQUEST')
        return self.execute(request.proposal)

    def execute(self, proposal: PythonProposal) -> dict[str, Any]:
        if not self._available:
            raise ExecutionUnavailable()
        return deepcopy(self._outcome)
