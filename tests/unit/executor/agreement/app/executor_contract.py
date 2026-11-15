"""Provisional, in-process handoff values; this module does not execute code."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol
from uuid import UUID

from app.proposals import PythonProposal, validate_proposals

MIN_TIMEOUT_SECONDS = 1
MAX_TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class ExecutorRequest:
    request_id: UUID
    run_id: UUID
    dataset_id: UUID
    proposal: PythonProposal = field(repr=False)
    timeout_seconds: int

    def __post_init__(self) -> None:
        if any(type(value) is not UUID for value in (self.request_id, self.run_id, self.dataset_id)):
            raise ValueError('INVALID_EXECUTOR_REQUEST')
        if (type(self.proposal) is not PythonProposal or type(self.proposal.code) is not str
                or '\x00' in self.proposal.code):
            raise ValueError('INVALID_EXECUTOR_REQUEST')
        validate_proposals([{'name': 'run_python', 'arguments': {'code': self.proposal.code}}])
        if type(self.timeout_seconds) is not int or not MIN_TIMEOUT_SECONDS <= self.timeout_seconds <= MAX_TIMEOUT_SECONDS:
            raise ValueError('INVALID_EXECUTOR_REQUEST')


class ExecutorStatus(Enum):
    """Outcome of a lifecycle operation, not an execution completion status."""

    ACCEPTED = 'accepted'
    REJECTED = 'rejected'
    UNKNOWN = 'unknown'


@dataclass(frozen=True)
class ExecutorResult:
    request_id: UUID
    run_id: UUID
    status: ExecutorStatus

    def __post_init__(self) -> None:
        if (type(self.request_id) is not UUID or type(self.run_id) is not UUID
                or type(self.status) is not ExecutorStatus):
            raise ValueError('INVALID_EXECUTOR_RESULT')


class RunState(Enum):
    QUEUED = 'queued'
    RUNNING = 'running'
    COMPLETED = 'completed'
    FAILED = 'failed'
    CANCELLED = 'cancelled'
    UNKNOWN = 'unknown'


class CleanupState(Enum):
    NOT_STARTED = 'not_started'
    PENDING = 'pending'
    CONFIRMED = 'confirmed'
    FAILED = 'failed'
    UNKNOWN = 'unknown'


@dataclass(frozen=True)
class ExecutorObservation:
    """Provider-reported states; they require independent provenance checks."""
    request_id: UUID
    run_id: UUID
    state: RunState
    cleanup: CleanupState

    def __post_init__(self) -> None:
        if (type(self.request_id) is not UUID or type(self.run_id) is not UUID
                or type(self.state) is not RunState or type(self.cleanup) is not CleanupState):
            raise ValueError('INVALID_EXECUTOR_OBSERVATION')


class FutureExecutor(Protocol):
    """Future provider interface only; no delivery or duplicate-safety guarantees.

    UNKNOWN means the outcome is unresolved and must be reconciled before retrying.
    ACCEPTED acknowledges an operation, not successful code execution or cleanup.
    Implementations must correlate and validate returned request and run IDs.
    """

    def submit(self, request: ExecutorRequest) -> ExecutorResult: ...

    def status(self, request_id: UUID, run_id: UUID) -> ExecutorObservation: ...

    def read_result(self, request_id: UUID, run_id: UUID) -> bytes:
        """Fetch untrusted result bytes; availability and transport are undecided."""
        ...

    def cancel(self, request_id: UUID, run_id: UUID) -> ExecutorResult: ...

    def cleanup(self, request_id: UUID, run_id: UUID) -> ExecutorResult: ...
