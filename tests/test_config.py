from __future__ import annotations

from pathlib import Path

from market_data_pipeline.config import load_config


def test_load_config_expands_default_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    config = load_config(Path("configs/pipeline.yml"))

    assert config.database.dsn.startswith("postgresql://market_user:")
    assert config.database.schema_path.name == "schema.sql"
    assert config.sources[0].name == "sample_daily_prices"
    assert config.sources[0].timezone.source == "America/New_York"
    assert [source.name for source in config.sources[1:]] == [
        "benchmark_100k",
        "benchmark_500k",
        "benchmark_1m",
    ]


def test_load_config_uses_database_url_from_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://example:secret@localhost:5432/custom")

    config = load_config(Path("configs/pipeline.yml"))

    assert config.database.dsn == "postgresql://example:secret@localhost:5432/custom"
