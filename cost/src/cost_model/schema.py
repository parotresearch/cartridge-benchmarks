"""Pydantic models for every input file: scenario, prices, coefficients, sizing, instances."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SYSTEMS = ("cartridge", "es_self_managed", "es_self_managed_enterprise_logsdb", "elastic_serverless")


class Retention(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hot_days: float = Field(ge=0)
    warm_days: float = Field(ge=0)
    frozen_days: float = Field(ge=0)


class QueryMix(BaseModel):
    """Share of queries answered by each tier (must sum to 1)."""

    model_config = ConfigDict(extra="forbid")
    hot: float = Field(ge=0, le=1)
    warm: float = Field(ge=0, le=1)
    frozen: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _sums_to_one(self) -> "QueryMix":
        total = self.hot + self.warm + self.frozen
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"query_mix must sum to 1, got {total}")
        return self


class Scenario(BaseModel):
    """Paths are relative to the cost/ directory unless absolute."""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    label: str
    tb_per_day: float = Field(gt=0, description="raw log text ingested per day, decimal TB")
    retention: Retention
    replicas: int = Field(ge=0, description="Elasticsearch / OpenSearch replica count on hot and warm")
    queries_per_day: float = Field(ge=0)
    query_window_days: float = Field(gt=0, description="days of data one query searches")
    query_mix: QueryMix
    region: str
    prices: Path = Path("data/prices.json")
    price_map: Path = Path("data/price_map.json")
    coefficients: Path = Path("data/coefficients.json")
    sizing: Path = Path("data/sizing.json")
    instances: Path = Path("data/instances.json")
    es_instance: str = Field(description="Elasticsearch / OpenSearch hot (and frozen) node type")
    es_warm_instance: str | None = Field(default=None, description="Elasticsearch warm-tier node type (default es_instance)")
    es_min_hot_nodes: int = Field(ge=1)
    target_cpu_utilization: float = Field(gt=0, le=1, description="CPU share the fleets are sized to run at")
    cartridge_build_instance: str = Field(description="Cartridge build-server node type")
    cartridge_query_instance: str = Field(description="Cartridge query-server node type")
    cartridge_query_nodes: int = Field(ge=1, description="fixed query fleet size (an assumption, not sized)")
    cartridge_local_days: float = Field(ge=0, description="days kept on the local gp3 copy")
    cartridge_local_headroom: float = Field(ge=0, description="free-space headroom on the local copy")
    cartridge_gets_per_query: float = Field(ge=0, description="S3 GETs per search, charged on every search (an assumption)")

    @model_validator(mode="after")
    def _mix_has_data(self) -> "Scenario":
        for tier in ("hot", "warm", "frozen"):
            if getattr(self.query_mix, tier) > 0 and getattr(self.retention, f"{tier}_days") == 0:
                raise ValueError(f"query_mix.{tier} > 0 but retention.{tier}_days == 0: no data to query on that tier")
        return self


class PriceEntry(BaseModel):
    """One price row: {item, unit, usd, source_url, accessed, notes}."""

    model_config = ConfigDict(extra="forbid")
    item: str
    unit: str
    usd: float | None = Field(ge=0, description="null = not publicly listed")
    source_url: str = Field(min_length=1)
    accessed: str
    notes: str | None = ""


class Tier(BaseModel):
    model_config = ConfigDict(extra="forbid")
    upto: float | None = Field(description="upper bound of this tier in the price's monthly unit; None = no bound")
    entry: PriceEntry


class PriceSheet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    region: str
    path: str
    entries: dict[str, PriceEntry]
    tiers: dict[str, list[Tier]] = Field(default_factory=dict)

    def get(self, item: str) -> PriceEntry:
        if item not in self.entries:
            raise KeyError(f"price id {item!r} is not mapped to a row of {self.path}; add it to price_map.json")
        return self.entries[item]

    def get_tiers(self, item: str) -> list[Tier]:
        if item not in self.tiers:
            raise KeyError(f"graduated price id {item!r} is not mapped to rows of {self.path}; add it to price_map.json")
        return self.tiers[item]


class Coefficient(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: float = Field(ge=0)
    unit: str
    derivation: str = Field(min_length=1)
    source: str = Field(min_length=1)


class CoefficientSet(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    schema_: Literal["cost-coefficients/1"] = Field(alias="schema")
    label: str
    systems: dict[str, dict[str, Coefficient]]

    def get(self, system: str, name: str) -> Coefficient:
        if name not in self.systems.get(system, {}):
            raise KeyError(f"coefficient {system}.{name} missing from the coefficients file")
        return self.systems[system][name]


class SizingRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: float
    unit: str
    source_url: str = Field(min_length=1)
    quote: str = Field(min_length=1)


class SizingSheet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rules: dict[str, SizingRule]

    def get(self, rule_id: str) -> SizingRule:
        if rule_id not in self.rules:
            raise KeyError(f"sizing rule {rule_id!r} missing from sizing.json")
        return self.rules[rule_id]


class InstanceSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    vcpu: int = Field(gt=0)
    mem_gib: float = Field(gt=0)
    local_nvme_gb: float = Field(default=0, ge=0, description="instance-store NVMe, included in the instance price")
    price_item: str
    source_url: str = Field(min_length=1)


class InstanceSheet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instances: dict[str, InstanceSpec]

    def get(self, name: str) -> InstanceSpec:
        if name not in self.instances:
            raise KeyError(f"instance {name!r} missing from instances.json")
        return self.instances[name]
