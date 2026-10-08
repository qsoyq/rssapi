from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class GithubTestSettings(BaseSettings):
    test_github_token: str | None = None

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class V2exTestSettings(BaseSettings):
    test_v2ex_token: str | None = None
    test_v2ex_session_key: str | None = None

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class Settings(BaseModel):
    github: GithubTestSettings = Field(default_factory=GithubTestSettings)
    v2ex: V2exTestSettings = Field(default_factory=V2exTestSettings)
