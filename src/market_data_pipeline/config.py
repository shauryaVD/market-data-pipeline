from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import time
from pathlib import Path
from typing import Any

import yaml

ENV_PATTERN = re.compile(r"\$\{([^}:]+)(?::-(.*?))?\}")


class ConfigError(ValueError):
    """Raised when the pipeline configuration is missing required values."""


@dataclass(frozen=True)
class DatabaseConfig:
    dsn: str
    schema_path: Path


@dataclass(frozen=True)
class LoggingConfig:
    level: str = "INFO"
    json: bool = True
    file_path: Path | None = None


@dataclass(frozen=True)
class RetentionConfig:
    pipeline_runs_days: int = 90


@dataclass(frozen=True)
class TimezoneConfig:
    source: str
    target: str = "UTC"


@dataclass(frozen=True)
class BusinessRules:
    allow_future_timestamps: bool = False
    require_positive_prices: bool = True
    require_non_negative_volume: bool = True
    require_high_low_envelope: bool = True


@dataclass(frozen=True)
class TradingCalendar:
    enabled: bool = False
    market_open: time = time(9, 30)
    market_close: time = time(16, 0)
    holidays: frozenset[str] = frozenset()


@dataclass(frozen=True)
class SourceConfig:
    name: str
    path: Path
    timezone: TimezoneConfig
    destination_table: str = "market_prices"
    columns: dict[str, str] = field(default_factory=dict)
    required_columns: list[str] = field(default_factory=list)
    business_rules: BusinessRules = field(default_factory=BusinessRules)
    trading_calendar: TradingCalendar = field(default_factory=TradingCalendar)


@dataclass(frozen=True)
class PipelineConfig:
    database: DatabaseConfig
    logging: LoggingConfig
    retention: RetentionConfig
    sources: list[SourceConfig]
    base_dir: Path


def load_config(config_path: str | Path) -> PipelineConfig:
    path = Path(config_path).expanduser().resolve()
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    expanded = _expand_env(raw)
    base_dir = path.parent.parent

    database_raw = _require_mapping(expanded, "database")
    database = DatabaseConfig(
        dsn=_require_str(database_raw, "dsn"),
        schema_path=_resolve_path(base_dir, _require_str(database_raw, "schema_path")),
    )

    logging_raw = expanded.get("logging", {})
    if not isinstance(logging_raw, dict):
        raise ConfigError("logging must be a mapping")
    file_path = logging_raw.get("file_path")
    logging_config = LoggingConfig(
        level=str(logging_raw.get("level", "INFO")).upper(),
        json=bool(logging_raw.get("json", True)),
        file_path=_resolve_path(base_dir, file_path) if file_path else None,
    )

    retention_raw = expanded.get("retention", {})
    if not isinstance(retention_raw, dict):
        raise ConfigError("retention must be a mapping")
    retention = RetentionConfig(
        pipeline_runs_days=int(retention_raw.get("pipeline_runs_days", 90)),
    )

    sources_raw = expanded.get("sources")
    if not isinstance(sources_raw, list) or not sources_raw:
        raise ConfigError("sources must contain at least one source")
    sources = [_parse_source(base_dir, item) for item in sources_raw]

    return PipelineConfig(
        database=database,
        logging=logging_config,
        retention=retention,
        sources=sources,
        base_dir=base_dir,
    )


def _parse_source(base_dir: Path, raw: Any) -> SourceConfig:
    if not isinstance(raw, dict):
        raise ConfigError("each source must be a mapping")

    timezone_raw = _require_mapping(raw, "timezone")
    columns = _require_mapping(raw, "columns")
    business_rules_raw = raw.get("business_rules", {})
    if not isinstance(business_rules_raw, dict):
        raise ConfigError("source.business_rules must be a mapping")
    trading_calendar_raw = raw.get("trading_calendar", {})
    if not isinstance(trading_calendar_raw, dict):
        raise ConfigError("source.trading_calendar must be a mapping")

    source = SourceConfig(
        name=_require_str(raw, "name"),
        path=_resolve_path(base_dir, _require_str(raw, "path")),
        timezone=TimezoneConfig(
            source=_require_str(timezone_raw, "source"),
            target=str(timezone_raw.get("target", "UTC")),
        ),
        destination_table=str(raw.get("destination_table", "market_prices")),
        columns={str(key): str(value) for key, value in columns.items()},
        required_columns=[str(column) for column in raw.get("required_columns", [])],
        business_rules=BusinessRules(
            allow_future_timestamps=bool(business_rules_raw.get("allow_future_timestamps", False)),
            require_positive_prices=bool(business_rules_raw.get("require_positive_prices", True)),
            require_non_negative_volume=bool(
                business_rules_raw.get("require_non_negative_volume", True)
            ),
            require_high_low_envelope=bool(
                business_rules_raw.get("require_high_low_envelope", True)
            ),
        ),
        trading_calendar=_parse_trading_calendar(trading_calendar_raw),
    )
    _validate_source(source)
    return source


def _parse_trading_calendar(raw: dict[str, Any]) -> TradingCalendar:
    return TradingCalendar(
        enabled=bool(raw.get("enabled", False)),
        market_open=_parse_time(str(raw.get("market_open", "09:30"))),
        market_close=_parse_time(str(raw.get("market_close", "16:00"))),
        holidays=frozenset(str(value) for value in raw.get("holidays", [])),
    )


def _parse_time(value: str) -> time:
    try:
        hour, minute = value.split(":", 1)
        return time(int(hour), int(minute))
    except ValueError as error:
        raise ConfigError(f"invalid time value {value!r}; expected HH:MM") from error


def _validate_source(source: SourceConfig) -> None:
    canonical_required = {
        "symbol",
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "currency",
    }
    missing_mappings = sorted(canonical_required - set(source.columns))
    if missing_mappings:
        raise ConfigError(
            f"source {source.name!r} is missing column mappings: {', '.join(missing_mappings)}"
        )

    if source.destination_table != "market_prices":
        raise ConfigError("only the market_prices destination_table is currently supported")


def _resolve_path(base_dir: Path, value: str | Path) -> Path:
    path = Path(str(value)).expanduser()
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def _expand_env(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _expand_env(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    if isinstance(value, str):
        return ENV_PATTERN.sub(_replace_env, value)
    return value


def _replace_env(match: re.Match[str]) -> str:
    name, default = match.group(1), match.group(2)
    if name in os.environ:
        return os.environ[name]
    if default is not None:
        return default
    raise ConfigError(f"environment variable {name} is required")


def _require_mapping(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"{key} must be a mapping")
    return value


def _require_str(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{key} must be a non-empty string")
    return value
