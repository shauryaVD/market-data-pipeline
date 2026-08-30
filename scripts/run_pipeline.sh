#!/usr/bin/env bash
set -euo pipefail

CONFIG_PATH="${PIPELINE_CONFIG:-configs/pipeline.yml}"

market-data-pipeline init-db --config "$CONFIG_PATH"
market-data-pipeline run --config "$CONFIG_PATH"
