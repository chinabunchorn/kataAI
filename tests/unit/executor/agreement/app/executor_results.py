"""Bounded decoding of untrusted JSON data, not execution verification.

This module never executes input and assigns no meaning or provenance to guest
fields. Callers must obtain execution status and metrics from a trusted source.
Exception messages are sanitized, but traceback frames can retain guest data;
callers must not log locals or persist tracebacks.
"""

import json
import math

# Provisional backend limits; the byte limit applies to the entire wire payload.
MAX_RESULT_BYTES = 32_768
MAX_RESULT_DEPTH = 16  # Root is depth zero.
MAX_RESULT_ITEMS = 4_096  # Includes root and all values, excluding object keys.
MAX_INTEGER_BITS = 1_024


class ExecutionResultError(ValueError):
    """A sanitized error; code is MALFORMED_EXECUTION_RESULT or TOO_LARGE."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _malformed():
    raise ExecutionResultError('MALFORMED_EXECUTION_RESULT')


def _too_large():
    raise ExecutionResultError('EXECUTION_RESULT_TOO_LARGE')


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _malformed()
        result[key] = value
    return result


def _integer(text):
    # Avoid constructing arbitrarily large integers before validating their size.
    if len(text.lstrip('-')) > 309:
        _too_large()
    value = int(text)
    if value.bit_length() > MAX_INTEGER_BITS:
        _too_large()
    return value


def _constant(_text):
    _malformed()


def decode_execution_result(raw: bytes):
    """Return the JSON value, including None for null; raise on invalid input.

    Only exact bytes are accepted. Duplicate keys, non-finite floats, invalid
    UTF-8 and unpaired Unicode surrogates are rejected. Structural limits are
    checked after parsing; parsing itself is bounded by MAX_RESULT_BYTES.
    """
    if type(raw) is not bytes:
        _malformed()
    if len(raw) > MAX_RESULT_BYTES:
        _too_large()
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs,
                           parse_int=_integer, parse_constant=_constant)
        stack = [(value, 0)]
        count = 0
        while stack:
            item, depth = stack.pop()
            count += 1
            if count > MAX_RESULT_ITEMS or depth > MAX_RESULT_DEPTH:
                _too_large()
            if type(item) is str:
                if '\x00' in item:
                    _malformed()
                item.encode('utf-8')  # Reject escaped unpaired surrogates.
            elif type(item) is float and not math.isfinite(item):
                _malformed()
            elif type(item) is list:
                stack.extend((child, depth + 1) for child in item)
            elif type(item) is dict:
                for key in item:
                    if '\x00' in key:
                        _malformed()
                    key.encode('utf-8')  # Validate keys without counting as values.
                stack.extend((child, depth + 1) for child in item.values())
        return value
    except ExecutionResultError:
        raise
    except RecursionError:
        _too_large()
    except (ValueError, UnicodeError, OverflowError):
        raise ExecutionResultError('MALFORMED_EXECUTION_RESULT') from None
