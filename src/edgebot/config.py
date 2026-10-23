from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class UniverseConfig(BaseModel):
    quote: str = "USDT"
    categories: list[str] = Field(default_factory=lambda: ["linear", "spot"])
    top_n_raw: int = 80
    min_turnover_usdt: float = 2_000_000
    max_spread_bps: float = 12.0
    blacklist: list[str] = Field(default_factory=list)
    prefer_linear: bool = True


class AnalyticsWeights(BaseModel):
    liquidity: float = 0.22
    microstructure: float = 0.12
    volatility: float = 0.16
    trend: float = 0.20
    momentum: float = 0.12
    relative_strength: float = 0.10
    volume_quality: float = 0.08


class AnalyticsGates(BaseModel):
    min_atr_pct: float = 0.004
    max_atr_pct: float = 0.045
    min_htf_slope_abs: float = 0.0008
    min_composite: float = 55.0
    max_abs_funding: float = 0.0015
    min_rvol: float = 0.7


class AnalyticsConfig(BaseModel):
    deep_scan_n: int = 40
    shortlist_n: int = 15
    entry_tf: int = 15
    htf: int = 60
    bars_entry: int = 300
    bars_htf: int = 200
    benchmark_symbol: str = "BTCUSDT"
    benchmark_category: str = "linear"
    weights: AnalyticsWeights = Field(default_factory=AnalyticsWeights)
    gates: AnalyticsGates = Field(default_factory=AnalyticsGates)


class OutputConfig(BaseModel):
    save_csv: bool = True


class AppConfig(BaseModel):
    universe: UniverseConfig = Field(default_factory=UniverseConfig)
    analytics: AnalyticsConfig = Field(default_factory=AnalyticsConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)


class EnvSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bybit_api_key: str = ""
    bybit_api_secret: str = ""
    bybit_testnet: bool = True
    bybit_data_host: str = "public"
    edgebot_demo: str = "auto"
    edgebot_data_dir: str = "./data"
    edgebot_config: str = "./config/default.yaml"


def load_config(path: str | Path | None = None) -> AppConfig:
    settings = EnvSettings()
    cfg_path = Path(path or settings.edgebot_config)
    if not cfg_path.is_absolute():
        cfg_path = ROOT / cfg_path
    if cfg_path.exists():
        raw: dict[str, Any] = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        return AppConfig.model_validate(raw)
    return AppConfig()


def get_settings() -> EnvSettings:
    return EnvSettings()


def data_dir() -> Path:
    settings = get_settings()
    path = Path(settings.edgebot_data_dir)
    if not path.is_absolute():
        path = ROOT / path
    path.mkdir(parents=True, exist_ok=True)
    return path
