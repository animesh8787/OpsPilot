from app.config import Settings


def test_defaults_are_offline_safe():
    s = Settings(_env_file=None)
    assert s.llm_provider == "mock"
    assert s.agent_max_tool_calls > 0
