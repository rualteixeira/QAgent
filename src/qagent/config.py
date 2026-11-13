"""Configuração do QAgent (CPS 7.7). O .env é carregado explicitamente."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]

load_dotenv(PROJECT_ROOT / ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="QAGENT_", extra="ignore")

    runs_dir: Path = PROJECT_ROOT / "runs"
    # G6: apagar no arranque da API as execuções terminadas há mais de N dias (runs/<id>/). 0 = nunca (omissão:
    # apagar evidência é irreversível, por isso é opt-in). As pastas de fases (f0, f5, codegen…) nunca são tocadas.
    runs_retention_days: int = 0
    capabilities_config: Path = PROJECT_ROOT / "config" / "capabilities.json"
    appium_mcp_version: str = "1.99.3"

    # F0: o arranque stdio demora ~33 s → servidor HTTP de longa duração (F0-registo 4.3).
    mcp_transport: Literal["http", "stdio"] = "http"
    mcp_http_url: str = "http://127.0.0.1:8080/sse"

    # Só para transport=stdio.
    appium_mcp_entry: Path = (
        PROJECT_ROOT / "tools" / "appium-mcp" / "node_modules" / "appium-mcp" / "dist" / "index.js"
    )
    android_home: str = r"C:\Android\Sdk"
    java_home: str = r"C:\Android\JDK"

    # API (F4). Sem chave por omissão: se vazio, as rotas protegidas respondem 503.
    api_keys: str = ""
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000"
    ios_remote_server_url: str | None = None

    @property
    def api_key_set(self) -> set[str]:
        return {k.strip() for k in self.api_keys.split(",") if k.strip()}

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def load_capabilities(self, platform: str) -> dict:
        data = json.loads(self.capabilities_config.read_text(encoding="utf-8"))
        return dict(data[platform])


def get_settings() -> Settings:
    return Settings()
