from app.utils.chinese import convert_to_traditional


def test_convert_to_traditional_simplified_to_traditional():
    simplified = "这里是简体中文"
    # 台灣標準字形（s2tw）：裡，不是 OpenCC 預設的裏。
    expected = "這裡是簡體中文"
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


def test_convert_to_traditional_uses_taiwan_forms_without_rewriting_words():
    try:
        import opencc  # noqa: F401
    except ImportError:
        return
    # 辨識結果「自動着脫裝置」在台灣是錯字；「軟件」是使用者講的詞，不改成「軟體」。
    assert convert_to_traditional("自动着脱装置为什么用软件") == "自動著脫裝置為什麼用軟件"
