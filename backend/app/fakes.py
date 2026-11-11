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

    def execute(self, proposal: PythonProposal) -> dict[str, Any]:
        if not self._available:
            raise ExecutionUnavailable()
        return deepcopy(self._outcome)
