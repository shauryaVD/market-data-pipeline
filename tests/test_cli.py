from __future__ import annotations

import json

from market_data_pipeline.cli import main


def test_validate_config_cli_outputs_source_names(capsys):
    exit_code = main(["validate-config", "--config", "configs/pipeline.yml"])

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["status"] == "ok"
    assert output["sources"] == [
        "sample_daily_prices",
        "benchmark_100k",
        "benchmark_500k",
        "benchmark_1m",
    ]
