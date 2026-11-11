"""Provisional validation of untrusted model tool proposals."""

from dataclasses import dataclass

MAX_CODE_BYTES = 16_384  # Provisional UTF-8 byte limit, not yet a team contract.


@dataclass(frozen=True)
class PythonProposal:
    code: str


class InvalidToolProposal(ValueError):
    def __init__(self) -> None:
        super().__init__('INVALID_TOOL_CALL')


def validate_proposals(proposals: object) -> PythonProposal:
    if not isinstance(proposals, list) or len(proposals) != 1:
        raise InvalidToolProposal()
    proposal = proposals[0]
    if not isinstance(proposal, dict) or set(proposal) != {'name', 'arguments'}:
        raise InvalidToolProposal()
    if proposal['name'] != 'run_python':
        raise InvalidToolProposal()
    arguments = proposal['arguments']
    if not isinstance(arguments, dict) or set(arguments) != {'code'}:
        raise InvalidToolProposal()
    code = arguments['code']
    if not isinstance(code, str) or not code.strip():
        raise InvalidToolProposal()
    try:
        code_size = len(code.encode('utf-8'))
    except UnicodeEncodeError:
        raise InvalidToolProposal() from None
    if code_size > MAX_CODE_BYTES:
        raise InvalidToolProposal()
    return PythonProposal(code=code)
