"""Provisional application-facing interfaces; no real providers."""

from typing import Protocol

from app.proposals import PythonProposal


class ModelPort(Protocol):
    def generate(self, question: str, columns: tuple[str, ...]) -> object: ...


class ExecutorPort(Protocol):
    def execute(self, proposal: PythonProposal) -> dict[str, object]: ...
