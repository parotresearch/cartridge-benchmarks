"""cost-oneyear: 30-day vs 365-day http_logs cost at 10 TB/day, via matrix.price_row / system_totals (no new formulas).

Writes results/cost/oneyear-10tb-httplogs.{json,md}.
"""

import json

import typer

from .load import COST_DIR, REPO_ROOT, load_inputs
from .matrix import DATASETS, price_row
from .model import build_params, line_items, system_totals

SCENARIOS = COST_DIR / "scenarios"
OUT = REPO_ROOT / "results" / "cost"
ds = DATASETS["http_logs (1998 World Cup web logs, 23.5 GB)"]
raw, std = ds["raw"], ds["standard"] / ds["raw"]
rows = {c: (k, b / raw) for c, k, b, _ in ds["rows"]}
OS, LDB, CART = "OpenSearch 3.9.0 default", "ES logsdb, free licence", "Cartridge (log files + field data)"


def price(tag: str) -> dict[str, float]:
    allhot, hf, hw = (load_inputs(SCENARIOS / f"10tb-{tag}{v}.yaml") for v in ("", "-hotfrozen", "-hotwarm"))
    b = build_params(allhot)
    return {
        "ES standard, all hot": system_totals(allhot, b, ["es_self_managed"])["es_self_managed"],
        "OpenSearch 3.9 default, all hot": price_row(allhot, b, *rows[OS], std),
        "ES logsdb, free licence, all hot": price_row(allhot, b, *rows[LDB], std),
        "ES hot/warm, free licence": system_totals(hw, build_params(hw), ["es_self_managed"])["es_self_managed"],
        "ES hot/frozen, Enterprise": system_totals(hf, build_params(hf), ["es_self_managed"])["es_self_managed"],
        "ES hot/frozen + logsdb, Enterprise": system_totals(hf, build_params(hf), ["es_self_managed_enterprise_logsdb"])["es_self_managed_enterprise_logsdb"],
        "Elastic Serverless (list)": system_totals(allhot, b, ["elastic_serverless"])["elastic_serverless"],
        "Cartridge (field data)": price_row(allhot, b, *rows[CART], std),
    }


def cartridge_lines(tag: str) -> list[tuple[str, float]]:
    items = line_items(load_inputs(SCENARIOS / f"10tb-{tag}.yaml"), systems=["cartridge"])
    return [(f"{r.component} ({r.quantity:,.0f} {r.unit})", r.usd_year) for r in items.sort_values("usd_year", ascending=False).itertuples()]


def to_markdown(r: dict[str, dict[str, float]]) -> str:
    cart30, cart365 = r["30d"]["Cartridge (field data)"], r["365d"]["Cartridge (field data)"]
    out = ["# One-year retention at 10 TB/day, web server logs (http_logs)\n",
           "Estimate only: the cost model as a calculator, no new benchmarks. 10 TB/day, on demand, us-east-2 AWS list prices, http_logs measured sizes "
           "(the same coefficients as the 30-day scenarios). The only change is retention: 365 days searchable instead of 30 "
           "(hot/warm and hot/frozen keep 7 hot days, the rest warm/frozen: 358 days). Cartridge keeps its 7-day local cache, so only S3 storage grows.\n",
           "Estimated cost per year; × is that system's cost divided by Cartridge's at the same retention.\n",
           "| system | $/yr, 30 days | × | $/yr, 365 days | × |", "|---|--:|--:|--:|--:|"]
    out += [f"| {k} | ${r['30d'][k]:,.0f} | {r['30d'][k] / cart30:.1f}× | ${r['365d'][k]:,.0f} | {r['365d'][k] / cart365:.1f}× |" for k in r["30d"]]
    out += ["\n## Cartridge line items at 365 days\n", "| item | $/yr |", "|---|--:|"]
    out += [f"| {name} | ${usd:,.0f} |" for name, usd in cartridge_lines("365d")]
    out += ["\n## Assumptions\n",
            "- Query load unchanged (100K queries/day, 1,000 GETs each); query_mix and the 4 query nodes are the 30-day assumptions, not re-sized for a year of data. Frozen/warm node counts do scale with data.",
            "- The Enterprise licence stays a flat $150K estimate. Serverless uses list-price ingest + retention for 365 days.",
            "- Elastic's 76% logsdb factor and OpenSearch's measured ratio are from the 1× http_logs measurements, assumed to hold at a year of data.",
            "\n## Command\n", "```", "uv run cost-oneyear", "```",
            "\nScenarios: `cost/scenarios/10tb-365d{,-hotfrozen,-hotwarm}.yaml` (copies of the 30-day files; only retention days and name/label changed)."]
    return "\n".join(out) + "\n"


def main() -> None:
    r = {"30d": price("30d"), "365d": price("365d")}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "oneyear-10tb-httplogs.json").write_text(json.dumps(r, indent=1) + "\n")
    md = to_markdown(r)
    (OUT / "oneyear-10tb-httplogs.md").write_text(md)
    print(md)


def cli() -> None:
    typer.run(main)
