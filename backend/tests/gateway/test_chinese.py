from app.utils.chinese import convert_to_traditional


def test_convert_to_traditional_simplified_to_traditional():
    simplified = "这里是简体中文"
    expected = "這裏是簡體中文"
    converted = convert_to_traditional(simplified)

    try:
        import opencc

        assert converted == expected
    except ImportError:
        assert converted == simplified


def test_convert_to_traditional_disabled(monkeypatch):
    import app.utils.chinese as chinese_module
    from types import SimpleNamespace

    monkeypatch.setattr(
        chinese_module,
        "get_tts_config",
        lambda: SimpleNamespace(gateway_convert_to_traditional=False),
    )

    simplified = "这里是简体中文"
    converted = convert_to_traditional(simplified)
    assert converted == simplified
