"""Shared settings for the backend (app), graph, tools, resolvers and db packages.

The Streamlit UI does NOT import this module — it only talks to the backend
over HTTP and has its own tiny config in streamlit_app/config.py.
"""
from __future__ import annotations

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    groq_api_key: str = ""
    groq_model: str = "qwen/qwen3-32b"

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "vn_agent"
    postgres_user: str = "vn_agent"
    postgres_password: str = "change_me"

    app_host: str = "0.0.0.0"
    app_port: int = 8000

    ticker_mapping_path: str = "data/tickers.json"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
