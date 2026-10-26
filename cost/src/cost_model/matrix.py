"""cost-matrix: yearly cost of every measured (dataset, store config) at one scenario, with the measured size as the only change.

Each row swaps the measured bytes/raw into the model's size coefficients and prices one system through the unchanged model:
Elasticsearch / OpenSearch configs through `es_self_managed` (self-managed, same sizing rules; OpenSearch has no Enterprise licence),
Enterprise logsdb through `es_self_managed_enterprise_logsdb` (adds the licence row), Cartridge through `cartridge`. Compute coefficients
stay the http_logs measurements (not re-measured per dataset); Cartridge rows without a field-data build carry no field-data bytes or build time.
Writes results/cost/matrix-<scenario>.{md,json}.
"""

import json
from pathlib import Path
from typing import Annotated

import pandas as pd
import typer
from rich.console import Console
from rich.table import Table

from .load import COST_DIR, REPO_ROOT, load_inputs
from .model import build_params, system_totals

RESULTS = REPO_ROOT / "results" / "cost"
DEFAULT_SCENARIO = COST_DIR / "scenarios" / "10tb-30d.yaml"
# (dataset, config, system-kind, stored bytes, source result file). kind: es | es_ent (value = synthetic-source bytes/raw; standard given separately) | cart | cart_no_field_data
DATASETS = {
    "http_logs (1998 World Cup web logs, 23.5 GB)": {
        "raw": 23_475_280_341,
        "rows": [
            ("ES standard (merged, ingest 2026-10-21)", "es", 22_547_013_768, "results/speed/tiers-b2e342779-1x-build-ingest-r7i-4xlarge-2026-10-21.log"),
            ("ES standard (merged, hot restore 2026-10-07; cost-model default)", "es", 18_656_019_625, "results/speed/scoreboard-31gb-tiers-2026-10-21.md"),
            ("OpenSearch 3.9.0 default", "es", 19_456_920_952, "results/speed/http-logs-1x-opensearch-default-3.9.0.md"),
            ("ES logsdb, free licence", "es", 10_567_779_983, "results/speed/http-logs-1x-logsdb-es954.md"),
            ("ES logsdb, Enterprise (synthetic source)", "es_ent", 6_485_137_851, "results/speed/http-logs-1x-logsdb-es954.md"),
            ("Cartridge (log files + field data)", "cart", 3_237_744_683, "results/speed/cartridge-s3aws-0ed622c29-cart-v4r-press-2026-10-23.log"),
        ],
        "standard": 22_547_013_768,
    },
    "CloudTrail flaws.cloud audit JSON (2.4 GB)": {
        "raw": 2_389_223_172,
        "rows": [
            ("ES standard + 4 flattened fields (the working standard setup)", "es", 1_438_882_886, "results/storage/cloudtrail-flaws-6bbd7038c-es955-vs-gron.md"),
            ("OpenSearch 3.9.0 default (flat_object fields)", "es", 1_476_093_976, "results/storage/opensearch-default-real-r7i-4xlarge-2026-10-26-flush.log"),
            ("ES flattened + logsdb", "es", 996_991_992, "results/storage/cloudtrail-flaws-6bbd7038c-es955-vs-gron.md"),
            ("ES stock logs data stream (logsdb; 20.9% of events partly unsearchable)", "es", 841_790_533, "results/storage/cloudtrail-flaws-6bbd7038c-es955-vs-gron.md"),
            ("Cartridge, larger output", "cart_no_field_data", 456_060_724, "results/storage/cloudtrail-flaws-6bbd7038c-es955-vs-gron.md"),
            ("Cartridge, smaller output", "cart_no_field_data", 389_109_483, "results/storage/cloudtrail-flaws-6bbd7038c-es955-vs-gron.md"),
        ],
        "standard": 1_438_882_886,
    },
    "Thunderbird supercomputer syslog (10.7 GB)": {
        "raw": 10_737_418_238,
        "rows": [
            ("ES standard", "es", 7_419_489_100, "results/storage/real-thunderbird10g-6bbd7038c-es955.md"),
            ("OpenSearch 3.9.0 default", "es", 7_388_032_630, "results/storage/opensearch-default-real-r7i-4xlarge-2026-10-26.log"),
            ("ES logsdb, free licence", "es", 2_400_695_754, "results/storage/real-thunderbird10g-6bbd7038c-es955.md"),
            ("Cartridge, larger output", "cart_no_field_data", 701_303_359, "results/storage/real-thunderbird10g-6bbd7038c-es955.md"),
            ("Cartridge, smaller output", "cart_no_field_data", 525_666_845, "results/storage/real-thunderbird10g-6bbd7038c-es955.md"),
        ],
        "standard": 7_419_489_100,
    },
    "CockroachDB JSON logs (10.5 GB)": {
        "raw": 10_506_623_721,
        "rows": [
            ("ES standard", "es", 9_682_259_352, "results/storage/real-cockroachdb-6bbd7038c-es955.md"),
            ("OpenSearch 3.9.0 default", "es", 3_722_426_390, "results/storage/opensearch-default-real-r7i-4xlarge-2026-10-26.log"),
            ("ES logsdb, free licence", "es", 1_506_138_614, "results/storage/real-cockroachdb-6bbd7038c-es955.md"),
            ("Cartridge, larger output", "cart_no_field_data", 766_850_694, "results/storage/real-cockroachdb-native-gron-73f8afaa2.md"),
            ("Cartridge, smaller output", "cart_no_field_data", 557_402_533, "results/storage/real-cockroachdb-native-gron-73f8afaa2.md"),
        ],
        "standard": 9_682_259_352,
    },
    "Alibaba microservice traces, OTel spans (19.7 GB)": {
        "raw": 19_744_374_361,
        "rows": [
            ("ES standard (stock traces-otel template, index.mode=standard)", "es", 5_200_242_650, "results/storage/traces-alibaba-cg2022-989c86f54-es955.md"),
            ("OpenSearch 3.9.0 default (flat_object attributes)", "es", 9_471_101_499, "results/storage/opensearch-default-real-r7i-4xlarge-2026-10-26-flush.log"),
            ("ES stock OTel trace stream (logsdb, free licence)", "es", 4_560_877_302, "results/storage/traces-alibaba-cg2022-989c86f54-es955.md"),
            ("Cartridge, larger output", "cart_no_field_data", 1_568_758_212, "results/storage/traces-alibaba-cg2022-989c86f54-es955.md"),
            ("Cartridge, smaller output", "cart_no_field_data", 1_048_451_721, "results/storage/traces-alibaba-cg2022-989c86f54-es955.md"),
        ],
        "standard": 5_200_242_650,
    },
}
SNAPSHOT_PER_INDEX = 1.0221  # the http_logs snapshot/index ratio the model already uses


def price_row(inputs, base: dict, kind: str, ratio: float, std_ratio: float) -> float:
    p = dict(base)
    match kind:
        case "es":
            p |= {"coef.elasticsearch.index_bytes_per_raw": ratio, "coef.elasticsearch.snapshot_bytes_per_raw": ratio * SNAPSHOT_PER_INDEX}
            return system_totals(inputs, p, ["es_self_managed"])["es_self_managed"]
        case "es_ent":
            p |= {"coef.elasticsearch.index_bytes_per_raw": std_ratio, "coef.elasticsearch.snapshot_bytes_per_raw": std_ratio * SNAPSHOT_PER_INDEX,
                  "coef.elasticsearch.logsdb_enterprise_retained_fraction": ratio / std_ratio}
            return system_totals(inputs, p, ["es_self_managed_enterprise_logsdb"])["es_self_managed_enterprise_logsdb"]
        case "cart":
            p |= {"coef.cartridge.files_bytes_per_raw": ratio}
        case "cart_no_field_data":
            p |= {"coef.cartridge.files_bytes_per_raw": ratio, "coef.cartridge.field_data_bytes_per_raw": 0.0, "coef.cartridge.field_data_core_s_per_raw_gb": 0.0}
    return system_totals(inputs, p, ["cartridge"])["cartridge"]


def matrix(scenario: Path) -> pd.DataFrame:
    inputs = load_inputs(scenario)
    base = build_params(inputs)
    rows = [
        {"dataset": ds, "config": cfg, "kind": kind, "bytes": b, "x_raw": b / d["raw"], "source": src,
         "usd_year": price_row(inputs, base, kind, b / d["raw"], d["standard"] / d["raw"])}
        for ds, d in DATASETS.items() for cfg, kind, b, src in d["rows"]
    ]
    df = pd.DataFrame(rows)
    cart_larger = df[df.kind.str.startswith("cart")].groupby("dataset").usd_year.max().rename("cart_larger_usd")
    cart_min = df[df.kind.str.startswith("cart")].groupby("dataset").usd_year.min().rename("cart_best_usd")
    cart_bytes = df[df.kind.str.startswith("cart")].groupby("dataset").bytes.max().rename("cart_larger_bytes")
    return (df.join(cart_larger, on="dataset").join(cart_min, on="dataset").join(cart_bytes, on="dataset")
              .assign(size_vs_cart=lambda d: d.bytes / d.cart_larger_bytes,
                      cost_vs_cart=lambda d: d.usd_year / d.cart_larger_usd,
                      cost_vs_cart_best=lambda d: d.usd_year / d.cart_best_usd))


def to_markdown(df: pd.DataFrame, scenario: str) -> str:
    out = [f"# Cost matrix: every measured dataset x store config ({scenario})\n",
           "Estimate only: the cost model as a calculator; measured bytes/raw are the only per-row change. "
           "Generated by `uv run cost-matrix` (cost/src/cost_model/matrix.py). "
           "\"Cartridge\" in the comparison columns is the larger of the two measured Cartridge outputs per dataset.\n"]
    for ds, g in df.groupby("dataset", sort=False):
        out += [f"\n## {ds}\n", "| config | stored B | x raw | size vs Cartridge | $/yr | cost vs Cartridge | cost vs best Cartridge |", "|---|---|---|---|---|---|---|"]
        out += [f"| {r.config} | {r.bytes:,} | {r.x_raw:.3f} | {r.size_vs_cart:.2f}x | ${r.usd_year:,.0f} | {r.cost_vs_cart:.2f}x | {r.cost_vs_cart_best:.2f}x |"
                for r in g.itertuples()]
        out += ["", "Sources: " + " · ".join(sorted(set(g.source)))]
    return "\n".join(out) + "\n"


def main(scenario: Annotated[Path, typer.Argument(exists=True, dir_okay=False)] = DEFAULT_SCENARIO) -> None:
    df = matrix(scenario)
    name = load_inputs(scenario).scenario.name
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f"matrix-{name}.md").write_text(to_markdown(df, name))
    (RESULTS / f"matrix-{name}.json").write_text(json.dumps(df.to_dict(orient="records"), indent=2) + "\n")
    t = Table("dataset", "config", "x raw", "$/yr", "vs Cartridge")
    for r in df.itertuples():
        t.add_row(r.dataset[:28], r.config[:58], f"{r.x_raw:.3f}", f"${r.usd_year:,.0f}", f"{r.cost_vs_cart:.2f}x")
    Console(width=180).print(t)


def cli() -> None:
    typer.run(main)
