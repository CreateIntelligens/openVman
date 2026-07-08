from app.config import TTSRouterConfig


def test_gemini_config_defaults():
    config = TTSRouterConfig(_env_file=None)
    assert config.tts_gemini_url == ""
