from app.utils.log_safe import log_safe


def test_log_safe_escapes_line_breaks():
    assert log_safe("a\r\nb\nc\rd") == "a\\nb\\nc\\rd"


def test_log_safe_keeps_plain_values():
    assert log_safe("plain value") == "plain value"
    assert log_safe(42) == "42"
    assert log_safe(None) == "None"
