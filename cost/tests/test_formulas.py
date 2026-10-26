"""Every system's yearly cost checked against hand-computed numbers (see conftest for the inputs)."""

import math

import pytest

from cost_model.model import build_params, line_items
from cost_model.schema import Tier

LICENCE = "Enterprise subscription (ESTIMATE, not a list price)"
HOT_DISK = 1000 * 10 * 2 * 0.5 / 0.85  # GB/day × hot days × copies × index/raw ÷ low watermark


def usd(items, system, component, tier=None):
    rows = items.query("system == @system and component == @component")
    if tier is not None:
        rows = rows.query("tier == @tier")
    assert len(rows) == 1, f"expected one row for {system}/{component}/{tier}, got {len(rows)}"
    return rows.usd_year.iloc[0]


def test_elastic_serverless_hand_computed(world):
    items = line_items(world(tb_per_day=0.1))
    assert usd(items, "elastic_serverless", "ingest") == pytest.approx(100 * 365 * 0.15)
    assert usd(items, "elastic_serverless", "retention") == pytest.approx(100 * 30 * 12 * 0.02)


def test_serverless_graduated_tiers(world):
    inputs = world(tb_per_day=0.1)
    t0 = inputs.prices.tiers["elastic.serverless.ingest_per_gb"][0].entry
    inputs.prices.tiers["elastic.serverless.ingest_per_gb"] = [
        Tier(upto=1000, entry=t0), Tier(upto=None, entry=t0.model_copy(update={"usd": 0.05}))]
    monthly = 100 * 365 / 12
    assert usd(line_items(inputs), "elastic_serverless", "ingest") == pytest.approx(12 * (1000 * 0.15 + (monthly - 1000) * 0.05))


def test_cartridge_hand_computed(world):
    items = line_items(world())
    assert usd(items, "cartridge", "S3 storage (Cartridge files + field data, every tier)") == pytest.approx(1000 * 30 * 0.15 * 12 * 0.02)
    assert usd(items, "cartridge", "EBS gp3 local copy") == pytest.approx(1000 * 10 * 0.15 * 1.25 * 12 * 0.1)
    # build: 1000 × 150 / 86400 / 0.5 = 3.47 cores -> 1 node; query fleet fixed at 2
    assert usd(items, "cartridge", "build nodes") == pytest.approx(8760 * 1.0)
    assert usd(items, "cartridge", "query nodes") == pytest.approx(2 * 8760 * 1.0)
    assert usd(items, "cartridge", "S3 PUT requests (upload)") == pytest.approx(1000 * 365 * 0.15 * 100 / 1000 * 0.005)
    assert usd(items, "cartridge", "S3 GET requests") == 0


def test_cartridge_gets_are_charged_on_every_search(world):
    items = line_items(world(queries_per_day=100, cartridge_gets_per_query=1000))
    assert usd(items, "cartridge", "S3 GET requests") == pytest.approx(100 * 365 * 1000 / 1000 * 0.001)


def test_field_data_build_adds_to_build_fleet(world):
    # 10 TB/day × (100 build + 50 field data) core-s/GB / 86400 / 0.5 / 8 vCPU = 4.34 -> 5 nodes; without field data 2.89 -> 3
    inputs = world(tb_per_day=10, retention={"hot_days": 1, "warm_days": 0, "frozen_days": 0})
    assert usd(line_items(inputs), "cartridge", "build nodes") == pytest.approx(5 * 8760)
    params = build_params(inputs) | {"coef.cartridge.field_data_core_s_per_raw_gb": 0.0}
    assert usd(line_items(inputs, params), "cartridge", "build nodes") == pytest.approx(3 * 8760)


def test_es_self_managed_hand_computed(world):
    items = line_items(world())
    # nodes = max(3, ceil(HOT_DISK / (64 × 30)) = 7, ceil(4.63 ingest cores / 8) = 1) = 7
    assert usd(items, "es_self_managed", "data nodes", "hot") == pytest.approx(7 * 8760 * 1.0)
    assert usd(items, "es_self_managed", "EBS gp3", "hot") == pytest.approx(HOT_DISK * 12 * 0.1)
    # frozen: 1000 × 20 × 0.5 = 10000 GB in S3; nodes ceil(10000 / (64 × 1500)) = 1; cache 10% = 1000 GB
    assert usd(items, "es_self_managed", "data nodes", "frozen") == pytest.approx(8760 * 1.0)
    assert usd(items, "es_self_managed", "S3 snapshot storage", "frozen") == pytest.approx(10000 * 12 * 0.02)
    assert usd(items, "es_self_managed", "EBS gp3 shared cache", "frozen") == pytest.approx(1000 * 12 * 0.1)
    assert usd(items, "es_self_managed", "S3 GET requests", "frozen") == 0
    assert not len(items.query("system == 'es_self_managed' and tier == 'warm'"))


def test_frozen_gets_scale_with_frozen_share(world):
    items = line_items(world(queries_per_day=100, query_window_days=0.5, query_mix={"hot": 0.5, "warm": 0.0, "frozen": 0.5}))
    assert usd(items, "es_self_managed", "S3 GET requests", "frozen") == pytest.approx(100 * 365 * 0.5 * 2 * 500 / 1000 * 0.001)


def test_es_ingest_drives_node_count(world):
    inputs = world(tb_per_day=100, retention={"hot_days": 0.01, "warm_days": 0, "frozen_days": 0})
    # ingest cores 100000 × 100 × 2 / 86400 / 0.5 = 463 -> ceil(463 / 8) nodes; storage needs only 1
    assert usd(line_items(inputs), "es_self_managed", "data nodes", "hot") == pytest.approx(math.ceil(100000 * 100 * 2 / 86400 / 0.5 / 8) * 8760)


def test_es_local_nvme_and_cross_az(world):
    items = line_items(world(es_instance="nvme", tb_per_day=10, retention={"hot_days": 30, "warm_days": 0, "frozen_days": 0}))
    # disk 10000 × 30 × 2 × 0.5 / 0.85 = 352,941 GB / 3750 per node = 94.1 -> 95 nodes (RAM: / (128 × 30) = 92)
    assert usd(items, "es_self_managed", "data nodes (local NVMe included)", "hot") == pytest.approx(95 * 8760 * 1.5)
    assert "EBS gp3" not in set(items.query("system == 'es_self_managed'").component)
    assert usd(items, "es_self_managed", "cross-AZ replication traffic", "hot") == pytest.approx(10000 * 365 * 2 * 0.01)


def test_es_warm_tier_on_dense_storage_instance(world):
    items = line_items(world(es_warm_instance="dense", retention={"hot_days": 10, "warm_days": 20, "frozen_days": 0}))
    # warm disk 1000 × 20 × 2 × 0.5 / 0.85 = 23,529 GB; RAM ceil(23529 / (96 × 160)) = 2, local NVMe ceil(23529 / 7500) = 4 -> 4
    assert usd(items, "es_self_managed", "data nodes (local NVMe included)", "warm") == pytest.approx(4 * 8760 * 1.5)
    assert usd(items, "es_self_managed", "data nodes", "hot") == pytest.approx(7 * 8760 * 1.0)


def test_enterprise_logsdb_variant_scales_es_storage(world):
    items = line_items(world())
    # logsdb variant: HOT_DISK × 0.25 = 2941 GB; nodes max(3, ceil(2941 / 1920) = 2, 1) = 3
    assert usd(items, "es_self_managed_enterprise_logsdb", "EBS gp3", "hot") == pytest.approx(HOT_DISK * 0.25 * 12 * 0.1)
    assert usd(items, "es_self_managed_enterprise_logsdb", "data nodes", "hot") == pytest.approx(3 * 8760)
    assert usd(items, "es_self_managed_enterprise_logsdb", "S3 snapshot storage", "frozen") == pytest.approx(2500 * 12 * 0.02)


def test_enterprise_features_add_licence_row(world):
    # frozen tier (searchable snapshots) -> Enterprise on both variants, marked as an estimate
    items = line_items(world())
    for system in ("es_self_managed", "es_self_managed_enterprise_logsdb"):
        row = items.query("system == @system and component == @LICENCE")
        assert len(row) == 1 and row.usd_year.iloc[0] == pytest.approx(100_000) and bool(row.estimate.iloc[0])
    # hot/warm only: the free-licence variant needs none; the logsdb variant still does (synthetic _source)
    items = line_items(world(retention={"hot_days": 10, "warm_days": 5, "frozen_days": 0}))
    assert not len(items.query("system == 'es_self_managed' and component == @LICENCE"))
    assert "synthetic _source" in items.query("system == 'es_self_managed_enterprise_logsdb' and component == @LICENCE").formula.iloc[0]


def test_missing_price_fails_loud(world):
    inputs = world(drop_price="aws.s3.get_per_1k")
    with pytest.raises(KeyError, match="aws.s3.get_per_1k"):
        line_items(inputs)


def test_query_mix_on_empty_tier_is_rejected(world):
    with pytest.raises(ValueError, match="no data to query"):
        world(query_mix={"hot": 0.5, "warm": 0.5, "frozen": 0.0})
