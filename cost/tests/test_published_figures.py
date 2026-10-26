"""The shipped scenarios, prices and measured sizes reproduce the headline figures of the cost page."""

import pytest

from cost_model.load import COST_DIR, load_inputs
from cost_model.matrix import DATASETS, price_row
from cost_model.model import build_params, system_totals

SCENARIO = COST_DIR / "scenarios" / "10tb-30d.yaml"
HTTP = DATASETS["http_logs (1998 World Cup web logs, 23.5 GB)"]


def http_row(config: str):
    kind, size = next((k, b) for c, k, b, _ in HTTP["rows"] if c == config)
    return kind, size / HTTP["raw"]


def test_http_logs_headline_costs():
    inputs = load_inputs(SCENARIO)
    base = build_params(inputs)
    std = HTTP["standard"] / HTTP["raw"]
    assert price_row(inputs, base, *http_row("Cartridge (log files + field data)"), std) == pytest.approx(112_538, abs=1)
    assert price_row(inputs, base, *http_row("OpenSearch 3.9.0 default"), std) == pytest.approx(1_961_039, abs=1)
    assert price_row(inputs, base, *http_row("ES logsdb, free licence"), std) == pytest.approx(1_095_187, abs=1)
    assert system_totals(inputs, base, ["elastic_serverless"])["elastic_serverless"] == pytest.approx(344_151, abs=1)


def test_every_shipped_scenario_loads():
    for path in sorted((COST_DIR / "scenarios").glob("*.yaml")):
        assert load_inputs(path).scenario.name == path.stem
