"""Strict report framing; guest fields are never authoritative host metadata."""

from .contract import EXITS, MAX_DEPTH, PROTOCOL, REPORT_BYTES, ContractError
from .staging import check_run_id
from .validation import encode_json, parse_json, validate_result


def make_report(run_id: str, pod_uid: str, code: str,
                script_exit_code: int | None, result: object = None) -> bytes:
    report = {"protocol": PROTOCOL, "run_id": run_id, "pod_uid": pod_uid,
              "code": code, "script_exit_code": script_exit_code}
    if code == "OK":
        report["result"] = result
    raw = encode_json(report)
    validate_report(raw, run_id=run_id, pod_uid=pod_uid)
    return raw


def validate_report(raw: bytes, *, run_id: str, pod_uid: str) -> dict:
    if not raw or len(raw) > REPORT_BYTES:
        raise ContractError("REPORT_INVALID", "missing or oversized report")
    try:
        report = parse_json(raw, byte_limit=REPORT_BYTES, depth_limit=MAX_DEPTH + 1)
        if type(report) is not dict:
            raise ValueError
        expected = {"protocol", "run_id", "pod_uid", "code", "script_exit_code"}
        if report.get("code") == "OK":
            expected.add("result")
        if set(report) != expected or report["protocol"] != PROTOCOL:
            raise ValueError
        check_run_id(run_id)
        if not pod_uid or len(pod_uid) > 128:
            raise ValueError
        if report["run_id"] != run_id or report["pod_uid"] != pod_uid:
            raise ContractError("RESULT_ORIGIN", "report identity mismatch")
        code = report["code"]
        if not isinstance(code, str) or code not in EXITS:
            raise ValueError
        child = report["script_exit_code"]
        if child is not None and (type(child) is not int or not -255 <= child <= 255):
            raise ValueError
        if code == "OK":
            if child != 0 or type(child) is not int:
                raise ValueError
            # The same semantic contract, now applied to canonical encoded data.
            validate_result(encode_json(report["result"]))
        elif code == "SCRIPT_FAILED":
            if child is None or child == 0:
                raise ValueError
        elif code.startswith("RESULT_") and child != 0:
            raise ValueError
        return report
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        if isinstance(exc, ContractError) and exc.code == "RESULT_ORIGIN":
            raise
        raise ContractError("REPORT_INVALID", "malformed or inconsistent report") from None
