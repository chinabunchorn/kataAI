"""Pure bounded JSON validation, shared by guest runner and host collector."""

import json
import math

from .contract import (
    ContractError, MAX_DEPTH, MAX_ITEMS, RESULT_BYTES, TOTAL_ITEMS,
)


def encode_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")).encode("utf-8", errors="strict")


def _pairs(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContractError("RESULT_JSON", "duplicate key")
        result[key] = value
    return result


def _constant(_: str) -> None:
    raise ContractError("RESULT_JSON", "nonstandard constant")


def parse_json(raw: bytes, *, byte_limit: int, depth_limit: int) -> object:
    """Bound bytes/depth before json.loads allocates containers or recurses."""
    if len(raw) > byte_limit:
        raise ContractError("RESULT_LIMIT", "byte cap")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise ContractError("RESULT_ENCODING") from None
    if not text.strip():
        raise ContractError("RESULT_EMPTY")
    depth = 0
    quoted = escaped = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > depth_limit:
                raise ContractError("RESULT_LIMIT", "depth cap")
        elif char in "]}":
            depth -= 1
    try:
        return json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)
    except (ValueError, RecursionError) as exc:
        if isinstance(exc, ContractError):
            raise
        raise ContractError("RESULT_JSON") from None


def _check_string(value: str) -> None:
    if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise ContractError("RESULT_SHAPE", "unpaired surrogate")


def validate_value(value: object) -> object:
    if type(value) not in (dict, list):
        raise ContractError("RESULT_SHAPE", "object or array root required")
    stack = [(value, 1)]
    total = 0
    while stack:
        item, depth = stack.pop()
        if type(item) in (dict, list):
            if depth > MAX_DEPTH or len(item) > MAX_ITEMS:
                raise ContractError("RESULT_LIMIT", "collection/depth cap")
            total += len(item)
            if total > TOTAL_ITEMS:
                raise ContractError("RESULT_LIMIT", "total entry cap")
            if type(item) is dict:
                for key in item:
                    if type(key) is not str:
                        raise ContractError("RESULT_SHAPE")
                    _check_string(key)
                children = item.values()
            else:
                children = item
            for child in children:
                stack.append((child, depth + 1))
        elif type(item) is str:
            _check_string(item)
        elif type(item) is float:
            if not math.isfinite(item):
                raise ContractError("RESULT_SHAPE", "nonfinite number")
        elif item is not None and type(item) not in (int, bool):
            raise ContractError("RESULT_SHAPE")
    return value


def validate_result(raw: bytes) -> object:
    return validate_value(parse_json(raw, byte_limit=RESULT_BYTES,
                                     depth_limit=MAX_DEPTH))
