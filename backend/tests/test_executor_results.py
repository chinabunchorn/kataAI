import pytest


def test_valid_json_null_is_a_value_not_an_error():
    from app.executor_results import decode_execution_result
    assert decode_execution_result(b'null') is None


def test_returns_generic_data_without_interpreting_guest_claims():
    from app.executor_results import decode_execution_result
    value = decode_execution_result(b'{"status":"success","metrics":{"duration":1},"result":[true,null]}')
    assert value == {'status': 'success', 'metrics': {'duration': 1}, 'result': [True, None]}


@pytest.mark.parametrize('raw', [
    b'', b'not json secret', b'"\xff"', b'{"x":1,"x":2}',
    b'{"x":{"y":1,"y":2}}', b'NaN', b'Infinity', b'-Infinity',
    b'1e999', b'"\\ud800"', b'\xef\xbb\xbfnull', b'0 trailing',
])
def test_malformed_data_raises_sanitized_error(raw):
    from app.executor_results import decode_execution_result, ExecutionResultError
    with pytest.raises(ExecutionResultError) as exc:
        decode_execution_result(raw)
    assert exc.value.code == 'MALFORMED_EXECUTION_RESULT'
    assert str(exc.value) == 'MALFORMED_EXECUTION_RESULT'


def test_rejects_non_bytes_without_evaluating_or_stringifying_object():
    from app.executor_results import decode_execution_result, ExecutionResultError
    class Hostile:
        def __str__(self):
            raise AssertionError('must not stringify')
    with pytest.raises(ExecutionResultError) as exc:
        decode_execution_result(Hostile())
    assert exc.value.code == 'MALFORMED_EXECUTION_RESULT'


def test_raw_byte_cap_counts_utf8_and_whitespace():
    from app.executor_results import decode_execution_result, ExecutionResultError, MAX_RESULT_BYTES
    assert decode_execution_result(b' ' * (MAX_RESULT_BYTES - 4) + b'null') is None
    with pytest.raises(ExecutionResultError) as exc:
        decode_execution_result(b' ' * (MAX_RESULT_BYTES - 3) + b'null')
    assert exc.value.code == 'EXECUTION_RESULT_TOO_LARGE'
    assert str(exc.value) == 'EXECUTION_RESULT_TOO_LARGE'


def test_depth_limit_has_exact_boundary():
    from app.executor_results import decode_execution_result, ExecutionResultError, MAX_RESULT_DEPTH
    valid = b'[' * MAX_RESULT_DEPTH + b'0' + b']' * MAX_RESULT_DEPTH
    assert decode_execution_result(valid) is not None
    with pytest.raises(ExecutionResultError) as exc:
        decode_execution_result(b'[' + valid + b']')
    assert exc.value.code == 'EXECUTION_RESULT_TOO_LARGE'


def test_item_limit_counts_root_values_and_object_keys():
    from app.executor_results import decode_execution_result, ExecutionResultError, MAX_RESULT_ITEMS
    assert len(decode_execution_result(b'[' + b'0,' * (MAX_RESULT_ITEMS - 2) + b'0]')) == MAX_RESULT_ITEMS - 1
    with pytest.raises(ExecutionResultError) as exc:
        decode_execution_result(b'[' + b'0,' * (MAX_RESULT_ITEMS - 1) + b'0]')
    assert exc.value.code == 'EXECUTION_RESULT_TOO_LARGE'
    with pytest.raises(ExecutionResultError) as exc:
        decode_execution_result(b'{' + b','.join(('"%d":0' % i).encode() for i in range(MAX_RESULT_ITEMS // 2)) + b'}')
    assert exc.value.code == 'EXECUTION_RESULT_TOO_LARGE'


def test_large_integer_and_extreme_nesting_fail_closed():
    from app.executor_results import decode_execution_result, ExecutionResultError
    for raw in (b'9' * 1000, b'[' * 2000 + b'0' + b']' * 2000):
        with pytest.raises(ExecutionResultError):
            decode_execution_result(raw)
