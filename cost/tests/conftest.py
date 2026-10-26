"""A tiny world with round numbers, so every formula can be checked by hand."""

import json
from pathlib import Path

import pytest
import yaml

from cost_model.load import load_inputs

PRICES = {
    "aws.ec2.std.hour": 1.0,
    "aws.ec2.nvme.hour": 1.5,
    "aws.ec2.dense.hour": 1.5,
    "aws.ebs.gp3.gb_month": 0.1,
    "aws.s3.standard.gb_month": 0.02,
    "aws.s3.get_per_1k": 0.001,
    "aws.s3.put_per_1k": 0.005,
    "aws.transfer.cross_az_per_gb_direction": 0.01,
    "elastic.self_managed.enterprise_licence.year": 100000.0,
    "elastic.serverless.ingest_per_gb": 0.15,
    "elastic.serverless.retention_per_gb_month": 0.02,
}
GRADUATED = ("elastic.serverless.ingest_per_gb", "elastic.serverless.retention_per_gb_month")

COEFS = {
    "elasticsearch": {
        "index_bytes_per_raw": 0.5,
        "snapshot_bytes_per_raw": 0.5,
        "ingest_core_s_per_raw_gb": 100.0,
        "query_core_s_per_query_per_raw_gb": 0.01,
        "frozen_s3_get_per_query_per_raw_gb": 2.0,
        "logsdb_enterprise_retained_fraction": 0.25,
    },
    "cartridge": {
        "files_bytes_per_raw": 0.1,
        "field_data_bytes_per_raw": 0.05,
        "build_core_s_per_raw_gb": 100.0,
        "field_data_core_s_per_raw_gb": 50.0,
        "s3_put_per_stored_gb": 100.0,
    },
}

SIZING = {
    "es.hot_ram_to_data": 30,
    "es.warm_ram_to_data": 160,
    "es.frozen_ram_to_data": 1500,
    "es.frozen_cache_fraction": 0.1,
    "es.low_watermark": 0.85,
    "es.replicas_across_azs": 1,
    "cartridge.node_disk_max_gb": 65536,
    "elastic.subscription.enterprise_features": 1,
    "es.warm_instance_profile": 74,
}

INSTANCES = {
    "std": {"vcpu": 8, "mem_gib": 64, "price_item": "aws.ec2.std.hour"},
    "nvme": {"vcpu": 16, "mem_gib": 128, "local_nvme_gb": 3750, "price_item": "aws.ec2.nvme.hour"},
    "dense": {"vcpu": 12, "mem_gib": 96, "local_nvme_gb": 7500, "price_item": "aws.ec2.dense.hour"},
}

BASE_SCENARIO = {
    "name": "unit",
    "label": "unit test",
    "tb_per_day": 1.0,
    "retention": {"hot_days": 10, "warm_days": 0, "frozen_days": 20},
    "replicas": 1,
    "queries_per_day": 0,
    "query_window_days": 1,
    "query_mix": {"hot": 1.0, "warm": 0.0, "frozen": 0.0},
    "region": "us-east-2",
    "es_instance": "std",
    "es_min_hot_nodes": 3,
    "target_cpu_utilization": 0.5,
    "cartridge_build_instance": "std",
    "cartridge_query_instance": "std",
    "cartridge_query_nodes": 2,
    "cartridge_local_days": 10,
    "cartridge_local_headroom": 0.25,
    "cartridge_gets_per_query": 0,
}


@pytest.fixture
def world(tmp_path: Path):
    """Returns make(drop_price=None, **scenario_overrides) -> Inputs."""

    def make(drop_price: str | None = None, **overrides):
        row = lambda k, v: {"item": k, "unit": "u", "usd": v, "source_url": "https://example.test/" + k, "accessed": "2026-10-24", "notes": ""}
        price_map = {"items": {k: k for k in PRICES if k not in GRADUATED and k != drop_price},
                     "graduated": {k: [{"item": k, "upto": None}] for k in GRADUATED}}
        files = {
            "price_map.json": price_map,
            "prices.json": {"region": "us-east-2", "prices": [row(k, v) for k, v in PRICES.items() if k != drop_price]},
            "coefs.json": {"schema": "cost-coefficients/1", "label": "unit",
                           "systems": {s: {k: {"value": v, "unit": "u", "derivation": "test", "source": "test"} for k, v in c.items()}
                                       for s, c in COEFS.items()}},
            "sizing.json": {"rules": {k: {"value": v, "unit": "u", "source_url": "https://example.test/rule", "quote": "test"} for k, v in SIZING.items()}},
            "instances.json": {"instances": {k: v | {"source_url": "https://example.test/" + k} for k, v in INSTANCES.items()}},
        }
        for name, doc in files.items():
            (tmp_path / name).write_text(json.dumps(doc))
        scenario = BASE_SCENARIO | {
            "prices": str(tmp_path / "prices.json"),
            "price_map": str(tmp_path / "price_map.json"),
            "coefficients": str(tmp_path / "coefs.json"),
            "sizing": str(tmp_path / "sizing.json"),
            "instances": str(tmp_path / "instances.json"),
        } | overrides
        path = tmp_path / "scenario.yaml"
        path.write_text(yaml.safe_dump(scenario))
        return load_inputs(path)

    return make
