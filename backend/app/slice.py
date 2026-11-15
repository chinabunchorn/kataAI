"""Provisional in-process port wiring, not an HTTP execution endpoint."""

from app.ports import ExecutorPort, ModelPort
from app.proposals import validate_proposals


def run_fake_slice(
    model: ModelPort, executor: ExecutorPort, question: str, columns: tuple[str, ...]
) -> dict[str, object]:
    proposal = validate_proposals(model.generate(question, columns))
    return executor.execute(proposal)
