"""Loaders: every file is validated on read; any missing or malformed field raises."""

import json
from dataclasses import dataclass
from pathlib import Path

import yaml

from .schema import CoefficientSet, InstanceSheet, PriceEntry, PriceSheet, Scenario, SizingSheet, Tier

COST_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = COST_DIR.parent


def resolve(p: Path) -> Path:
    return p if p.is_absolute() else COST_DIR / p


def load_scenario(path: Path) -> Scenario:
    return Scenario.model_validate(yaml.safe_load(path.read_text()))


def _mapped_row(rows: dict[str, PriceEntry], model_id: str, name: str, path: Path) -> PriceEntry:
    if name not in rows:
        raise KeyError(f"price_map: {model_id} -> {name!r}, but {path} has no row with that item name")
    row = rows[name]
    if row.usd is None:
        raise ValueError(f"price_map: {model_id} -> {name!r} has usd null (not publicly listed) in {path}; it cannot be priced")
    return row


def load_prices(path: Path, map_path: Path) -> PriceSheet:
    """The price sheet ({region, prices: [{item, unit, usd, source_url, accessed, notes}]}) read through the explicit
    model-id -> item-name table in price_map.json. Every mapped row must exist and carry a price."""
    raw = json.loads(path.read_text())
    if not isinstance(raw, dict) or "region" not in raw or "prices" not in raw:
        raise ValueError(f"{path}: price sheet must be a JSON object with 'region' and a 'prices' list")
    rows = [PriceEntry.model_validate(r) for r in raw["prices"]]
    dupes = sorted({r.item for r in rows if sum(x.item == r.item for x in rows) > 1})
    if dupes:
        raise ValueError(f"{path}: duplicate price items {dupes}")
    by_name = {r.item: r for r in rows}
    mapping = json.loads(map_path.read_text())
    entries = {mid: _mapped_row(by_name, mid, name, path) for mid, name in mapping["items"].items()}
    tiers = {
        mid: [Tier(upto=t["upto"], entry=_mapped_row(by_name, mid, t["item"], path)) for t in spec]
        for mid, spec in mapping["graduated"].items()
    }
    for mid, ts in tiers.items():
        bounds = [t.upto for t in ts]
        if bounds[-1] is not None or any(b is None for b in bounds[:-1]) or bounds[:-1] != sorted(bounds[:-1]):
            raise ValueError(f"price_map: graduated {mid} needs ascending bounds ending in null, got {bounds}")
    return PriceSheet(region=raw["region"], path=str(path), entries=entries, tiers=tiers)


@dataclass(frozen=True)
class Inputs:
    scenario: Scenario
    prices: PriceSheet
    coefficients: CoefficientSet
    sizing: SizingSheet
    instances: InstanceSheet


def load_inputs(scenario_path: Path) -> Inputs:
    scenario = load_scenario(scenario_path)
    prices = load_prices(resolve(scenario.prices), resolve(scenario.price_map))
    if prices.region != scenario.region:
        raise ValueError(f"scenario region {scenario.region} != price sheet region {prices.region} ({prices.path})")
    return Inputs(
        scenario=scenario,
        prices=prices,
        coefficients=CoefficientSet.model_validate(json.loads(resolve(scenario.coefficients).read_text())),
        sizing=SizingSheet.model_validate(json.loads(resolve(scenario.sizing).read_text())),
        instances=InstanceSheet.model_validate(json.loads(resolve(scenario.instances).read_text())),
    )
