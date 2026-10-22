from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_provider: str = "mock"  # anthropic | ollama | mock
    llm_model: str = ""  # empty -> provider default
    anthropic_api_key: str = ""
    ollama_url: str = "http://localhost:11434"

    slack_bot_token: str = ""
    slack_app_token: str = ""
    slack_channel: str = "#incidents"

    prometheus_url: str = "http://localhost:9090"
    log_file: str = "data/demo_service.log"
    runbooks_dir: str = "runbooks"
    runbook_base_url: str = "https://github.com/your-user/opspilot/blob/main/runbooks"
    database_url: str = "sqlite:///data/opspilot.db"

    agent_max_tool_calls: int = 8
    agent_timeout_s: float = 60.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
