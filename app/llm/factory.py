from app.config import Settings
from app.llm.base import LLMProvider


def make_provider(s: Settings) -> LLMProvider:
    if s.llm_provider == "anthropic":
        from app.llm.anthropic_provider import AnthropicProvider

        return AnthropicProvider(s.anthropic_api_key, s.llm_model)
    if s.llm_provider == "ollama":
        from app.llm.ollama_provider import OllamaProvider

        return OllamaProvider(s.ollama_url, s.llm_model)
    if s.llm_provider == "mock":
        from app.llm.mock_provider import MockProvider

        return MockProvider()
    raise ValueError(f"unknown LLM_PROVIDER {s.llm_provider!r} (anthropic | ollama | mock)")
