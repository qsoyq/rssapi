from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class GithubTestSettings(BaseSettings):
    test_github_token: str | None = None

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


class Settings(BaseModel):
    github: GithubTestSettings = GithubTestSettings()
