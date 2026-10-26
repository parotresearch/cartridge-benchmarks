"""Yearly cost per system as a table of line items. Each row carries its formula and its source references.

All model inputs that can vary live in a flat `params` dict:
  input.<name>              scenario inputs (tb_per_day, hot_days, ..., query_window_days)
  coef.<system>.<name>      measured coefficients
Prices, sizing rules, instance specs and the scenario's fleet choices are fixed per run and read from `Inputs`.

Source reference strings (every row has at least one):
  input:<name>  coef:<system>.<name>  price:<id>  sizing:<rule>  instance:<name>
"""

import math
from collections.abc import Callable
from dataclasses import asdict, dataclass, field

import pandas as pd

from .load import Inputs
from .schema import InstanceSpec

HOURS_PER_YEAR = 24 * 365
MONTHS_PER_YEAR = 12
DAYS_PER_YEAR = 365
SECONDS_PER_DAY = 86_400
GB_PER_TB = 1000

INTEGER_INPUTS = {"replicas"}
LOGSDB_COEF = "logsdb_enterprise_retained_fraction"
ENTERPRISE_LICENCE = "elastic.self_managed.enterprise_licence.year"
ENTERPRISE_RULE = "sizing:elastic.subscription.enterprise_features"


def build_params(inputs: Inputs) -> dict[str, float]:
    s = inputs.scenario
    params = {
        "input.tb_per_day": s.tb_per_day,
        "input.hot_days": s.retention.hot_days,
        "input.warm_days": s.retention.warm_days,
        "input.frozen_days": s.retention.frozen_days,
        "input.replicas": float(s.replicas),
        "input.queries_per_day": s.queries_per_day,
        "input.query_window_days": s.query_window_days,
    }
    params |= {
        f"coef.{system}.{name}": c.value
        for system, coefs in inputs.coefficients.systems.items()
        for name, c in coefs.items()
    }
    return params


@dataclass
class Row:
    system: str
    component: str
    tier: str
    quantity: float
    unit: str
    unit_usd: float
    per_year: float
    formula: str
    sources: list[str] = field(default_factory=list)
    estimate: bool = False  # priced from a cited estimate, not a list price

    @property
    def usd_year(self) -> float:
        return self.quantity * self.unit_usd * self.per_year


@dataclass
class Ctx:
    inputs: Inputs
    p: dict[str, float]

    def inp(self, key: str) -> float:
        v = self.p[f"input.{key}"]
        return float(math.floor(v + 0.5)) if key in INTEGER_INPUTS else v

    def coef(self, system: str, name: str) -> float:
        return self.p[f"coef.{system}.{name}"]

    def rule(self, rule_id: str) -> float:
        return self.inputs.sizing.get(rule_id).value

    def price(self, item: str) -> float:
        usd = self.inputs.prices.get(item).usd
        assert usd is not None  # load_prices rejects null prices on every mapped row
        return usd

    def gb_per_day(self) -> float:
        return self.inp("tb_per_day") * GB_PER_TB

    def searched_gb(self) -> float:
        return self.gb_per_day() * self.inp("query_window_days")

    def mix(self, tier: str) -> float:
        return getattr(self.inputs.scenario.query_mix, tier)

    def util(self) -> float:
        return self.inputs.scenario.target_cpu_utilization

    def instance(self, name: str) -> InstanceSpec:
        return self.inputs.instances.get(name)


def line(
    ctx: Ctx,
    system: str,
    component: str,
    tier: str,
    qty: float,
    unit: str,
    price_item: str,
    per_year: float,
    per_year_label: str,
    qty_formula: str,
    sources: list[str],
) -> Row:
    usd = ctx.price(price_item)
    formula = f"[{qty_formula}] = {qty:,.4g} {unit} × ${usd:g} ({price_item}) × {per_year_label}"
    return Row(system, component, tier, qty, unit, usd, per_year, formula, [*sources, f"price:{price_item}"])


def graduated_line(ctx: Ctx, system: str, component: str, qty_month: float, unit: str, price_id: str, qty_formula: str,
                   sources: list[str]) -> Row:
    """Graduated (tiered) monthly pricing: each slice of the monthly quantity is billed at its tier's rate."""
    tiers = ctx.inputs.prices.get_tiers(price_id)
    lower, cost, parts = 0.0, 0.0, []
    for t in tiers:
        upper = math.inf if t.upto is None else t.upto
        slice_qty = max(0.0, min(qty_month, upper) - lower)
        if slice_qty > 0:
            assert t.entry.usd is not None
            cost += slice_qty * t.entry.usd
            parts.append(f"{slice_qty:,.0f} × ${t.entry.usd:g}")
        lower = upper
    blended = cost / qty_month if qty_month else 0.0
    formula = f"[{qty_formula}] = {qty_month:,.4g} {unit}/month, graduated ({' + '.join(parts) or '0'}) = ${cost:,.0f}/month × 12 mo"
    return Row(system, component, "all", qty_month, unit, blended, MONTHS_PER_YEAR, formula, [*sources, f"price:{price_id}"])


def ceil_pos(x: float) -> int:
    return math.ceil(x - 1e-9) if x > 0 else 0


# ------------------------------------------------------------------ shared Elasticsearch-style sizing (Elastic's guidance)


@dataclass
class EsSizing:
    hot_disk_gb: float
    warm_disk_gb: float
    frozen_s3_gb: float
    frozen_cache_gb: float
    ingest_cores: float
    hot_query_cores: float
    warm_query_cores: float
    frozen_query_cores: float
    formulas: dict[str, str]


ES_SIZING_SOURCES = ["input:tb_per_day", "input:replicas", "coef:elasticsearch.index_bytes_per_raw"]
HEADROOM_SRC = "sizing:es.low_watermark"


def es_sizing(ctx: Ctx, logsdb: bool = False) -> EsSizing:
    """logsdb=True is the 'Enterprise logsdb' variant: the measured (free-licence) index and snapshot sizes
    times Elastic's published logsdb retained fraction. logsdb=False is the measured free-licence variant."""
    g, r = ctx.gb_per_day(), ctx.inp("replicas")
    keep = ctx.coef("elasticsearch", LOGSDB_COEF) if logsdb else 1.0
    idx = ctx.coef("elasticsearch", "index_bytes_per_raw") * keep
    snap = ctx.coef("elasticsearch", "snapshot_bytes_per_raw") * keep
    wm = ctx.rule("es.low_watermark")
    factor, factor_f = 1 / wm, f"/ {wm:g} low watermark"
    util = ctx.util()
    q_cs = ctx.coef("elasticsearch", "query_core_s_per_query_per_raw_gb")
    ingest_cs = ctx.coef("elasticsearch", "ingest_core_s_per_raw_gb")
    hot, warm, frozen = ctx.inp("hot_days"), ctx.inp("warm_days"), ctx.inp("frozen_days")
    qpd, searched = ctx.inp("queries_per_day"), ctx.searched_gb()
    idx_f = f"{idx:.4g} index/raw{f' (measured × logsdb retained {keep:.4g})' if logsdb else ''}"

    def q_cores(tier: str) -> float:
        return qpd * ctx.mix(tier) * q_cs * searched / SECONDS_PER_DAY / util

    frozen_s3 = g * frozen * snap
    return EsSizing(
        hot_disk_gb=g * hot * (r + 1) * idx * factor,
        warm_disk_gb=g * warm * (r + 1) * idx * factor,
        frozen_s3_gb=frozen_s3,
        frozen_cache_gb=frozen_s3 * ctx.rule("es.frozen_cache_fraction"),
        ingest_cores=g * ingest_cs * (r + 1) / SECONDS_PER_DAY / util,
        hot_query_cores=q_cores("hot"),
        warm_query_cores=q_cores("warm"),
        frozen_query_cores=q_cores("frozen"),
        formulas={
            "hot_disk": f"{g:g} GB/day × {hot:g} hot days × ({r:g}+1) copies × {idx_f} {factor_f}",
            "warm_disk": f"{g:g} GB/day × {warm:g} warm days × ({r:g}+1) copies × {idx_f} {factor_f}",
            "frozen_s3": f"{g:g} GB/day × {frozen:g} frozen days × {snap:.4g} snapshot/raw"
                         f"{f' (measured × logsdb retained {keep:.4g})' if logsdb else ''}",
            "ingest_cores": f"{g:g} GB/day × {ingest_cs:.4g} core-s/GB × ({r:g}+1) copies / 86400 / {util:g} util",
        },
    )


def tier_nodes(ram_data_gb: float, local_gb: float, inst: InstanceSpec, ratio: float, cores: float, minimum: int) -> tuple[int, str]:
    """Nodes for one Elasticsearch-style tier: the largest of the minimum, Elastic's RAM:data ratio, the instance's
    local NVMe capacity (when it has local NVMe), and CPU."""
    if ram_data_gb <= 0 and cores <= 0:
        return 0, "0 (tier empty)"
    by_ram = ceil_pos(ram_data_gb / (inst.mem_gib * ratio))
    by_disk = ceil_pos(local_gb / inst.local_nvme_gb) if inst.local_nvme_gb else 0
    by_cpu = ceil_pos(cores / inst.vcpu)
    n = max(minimum, by_ram, by_disk, by_cpu)
    disk_f = f", local NVMe ceil({local_gb:,.0f} GB / {inst.local_nvme_gb:g} GB) = {by_disk}" if inst.local_nvme_gb else ""
    return n, (f"max(min {minimum}, RAM ceil({ram_data_gb:,.0f} GB / ({inst.mem_gib:g} GiB × {ratio:g})) = {by_ram}{disk_f}, "
               f"CPU ceil({cores:.3g} cores / {inst.vcpu} vCPU) = {by_cpu}) = {n}")


def enterprise_features(ctx: Ctx, logsdb: bool) -> list[str]:
    """The features in this configuration that Elastic's subscription matrix reserves for Enterprise."""
    return [
        *(["synthetic _source (logsdb storage savings)"] if logsdb else []),
        *(["frozen tier (searchable snapshots)"] if ctx.inp("frozen_days") > 0 else []),
    ]


def licence_row(ctx: Ctx, sys: str, features: list[str]) -> Row:
    row = line(ctx, sys, "Enterprise subscription (ESTIMATE, not a list price)", "all", 1, "cluster", ENTERPRISE_LICENCE, 1,
               "1 (already per year)",
               f"1 cluster; Enterprise needed for {' and '.join(features)}; Elastic publishes no self-managed price, so this is "
               f"Vendr's published floor ('commonly start at $150,000+ annually'; the real price is a sales quote)",
               [ENTERPRISE_RULE])
    row.estimate = True
    return row


# ------------------------------------------------------------------ systems


def es_self_managed(ctx: Ctx, logsdb: bool = False) -> list[Row]:
    """Self-managed Elasticsearch on EC2. Also prices OpenSearch: same sizing rules, a different measured size, no licence."""
    sys = "es_self_managed_enterprise_logsdb" if logsdb else "es_self_managed"
    sz = es_sizing(ctx, logsdb)
    sc = ctx.inputs.scenario
    inst_name = sc.es_instance
    inst = ctx.instance(inst_name)
    local = inst.local_nvme_gb > 0
    r = ctx.inp("replicas")
    min_hot = max(sc.es_min_hot_nodes, int(r) + 1)
    hot_nodes, hot_nf = tier_nodes(sz.hot_disk_gb, sz.hot_disk_gb, inst, ctx.rule("es.hot_ram_to_data"),
                                   sz.ingest_cores + sz.hot_query_cores, min_hot)
    warm_name = sc.es_warm_instance or inst_name
    warm_inst = ctx.instance(warm_name)
    warm_local = warm_inst.local_nvme_gb > 0
    warm_nodes, warm_nf = tier_nodes(sz.warm_disk_gb, sz.warm_disk_gb, warm_inst, ctx.rule("es.warm_ram_to_data"), sz.warm_query_cores, 1)
    frozen_nodes, frozen_nf = tier_nodes(sz.frozen_s3_gb, sz.frozen_cache_gb, inst, ctx.rule("es.frozen_ram_to_data"),
                                         sz.frozen_query_cores, 1)
    node_src = [f"instance:{inst_name}", "input:target_cpu_utilization", "coef:elasticsearch.ingest_core_s_per_raw_gb", HEADROOM_SRC,
                "coef:elasticsearch.query_core_s_per_query_per_raw_gb", "input:queries_per_day", "input:query_window_days"]
    rows = [
        line(ctx, sys, "data nodes" + (" (local NVMe included)" if local else ""), "hot", hot_nodes, "nodes", inst.price_item,
             HOURS_PER_YEAR, "8760 h/yr", f"{hot_nf}; hot_disk = {sz.formulas['hot_disk']}; ingest = {sz.formulas['ingest_cores']}",
             [*ES_SIZING_SOURCES, *node_src, "input:hot_days", "sizing:es.hot_ram_to_data", "input:es_min_hot_nodes"]),
    ]
    if not local:
        rows.append(line(ctx, sys, "EBS gp3", "hot", sz.hot_disk_gb, "GB", "aws.ebs.gp3.gb_month", MONTHS_PER_YEAR, "12 mo",
                         sz.formulas["hot_disk"], [*ES_SIZING_SOURCES, HEADROOM_SRC, "input:hot_days"]))
    if r > 0:
        g = ctx.gb_per_day()
        rows.append(line(ctx, sys, "cross-AZ replication traffic", "hot", g * DAYS_PER_YEAR * r * 2, "GB-direction",
                         "aws.transfer.cross_az_per_gb_direction", 1, "1 (already per year)",
                         f"{g:g} GB/day × 365 × {r:g} replica(s) in another AZ × 2 directions (out of one AZ, into the other)",
                         ["input:tb_per_day", "input:replicas", "sizing:es.replicas_across_azs"]))
    if warm_nodes:
        warm_src = [f"instance:{warm_name}", *(["input:es_warm_instance", "sizing:es.warm_instance_profile"] if sc.es_warm_instance else [])]
        rows.append(line(ctx, sys, "data nodes" + (" (local NVMe included)" if warm_local else ""), "warm", warm_nodes, "nodes",
                         warm_inst.price_item, HOURS_PER_YEAR, "8760 h/yr", f"{warm_nf}; warm_disk = {sz.formulas['warm_disk']}",
                         [*ES_SIZING_SOURCES, *node_src[1:], *warm_src, "input:warm_days", "sizing:es.warm_ram_to_data"]))
        if not warm_local:
            rows.append(line(ctx, sys, "EBS gp3", "warm", sz.warm_disk_gb, "GB", "aws.ebs.gp3.gb_month", MONTHS_PER_YEAR, "12 mo",
                             sz.formulas["warm_disk"], [*ES_SIZING_SOURCES, HEADROOM_SRC, "input:warm_days"]))
    if frozen_nodes:
        frozen_src = ["input:tb_per_day", "input:frozen_days", "coef:elasticsearch.snapshot_bytes_per_raw"]
        rows += [
            line(ctx, sys, "data nodes", "frozen", frozen_nodes, "nodes", inst.price_item, HOURS_PER_YEAR, "8760 h/yr",
                 f"{frozen_nf}; frozen_s3 = {sz.formulas['frozen_s3']}; cache = frozen_s3 × {ctx.rule('es.frozen_cache_fraction'):g}",
                 [*node_src, *frozen_src, "sizing:es.frozen_ram_to_data", "sizing:es.frozen_cache_fraction"]),
            line(ctx, sys, "S3 snapshot storage", "frozen", sz.frozen_s3_gb, "GB", "aws.s3.standard.gb_month", MONTHS_PER_YEAR, "12 mo",
                 sz.formulas["frozen_s3"], frozen_src),
            frozen_gets_row(ctx, sys),
        ]
        if not local:
            rows.append(line(ctx, sys, "EBS gp3 shared cache", "frozen", sz.frozen_cache_gb, "GB", "aws.ebs.gp3.gb_month", MONTHS_PER_YEAR,
                             "12 mo", f"frozen_s3 × {ctx.rule('es.frozen_cache_fraction'):g}; frozen_s3 = {sz.formulas['frozen_s3']}",
                             [*frozen_src, "sizing:es.frozen_cache_fraction"]))
    if features := enterprise_features(ctx, logsdb):
        rows.append(licence_row(ctx, sys, features))
    return rows


def frozen_gets_row(ctx: Ctx, sys: str) -> Row:
    coef_name = "frozen_s3_get_per_query_per_raw_gb"
    share = ctx.mix("frozen")
    per = ctx.coef("elasticsearch", coef_name)
    gets = ctx.inp("queries_per_day") * DAYS_PER_YEAR * share * per * ctx.searched_gb()
    f = (f"{ctx.inp('queries_per_day'):g} q/day × 365 × {share:g} (frozen share) × "
         f"{per:.4g} GETs/(q·GB) × {ctx.searched_gb():g} GB searched / 1000")
    return line(ctx, sys, "S3 GET requests", "frozen", gets / 1000, "1k requests", "aws.s3.get_per_1k", 1, "1 (already per year)", f,
                ["input:queries_per_day", "input:query_window_days", "input:tb_per_day", f"coef:elasticsearch.{coef_name}"])


def cartridge(ctx: Ctx) -> list[Row]:
    sys = "cartridge"
    sc = ctx.inputs.scenario
    g = ctx.gb_per_day()
    total = ctx.inp("hot_days") + ctx.inp("warm_days") + ctx.inp("frozen_days")
    local_days, over = sc.cartridge_local_days, sc.cartridge_local_headroom
    files = ctx.coef("cartridge", "files_bytes_per_raw")
    side = ctx.coef("cartridge", "field_data_bytes_per_raw")
    store = files + side
    util = ctx.util()
    build_cs = ctx.coef("cartridge", "build_core_s_per_raw_gb")
    side_cs = ctx.coef("cartridge", "field_data_core_s_per_raw_gb")
    qpd = ctx.inp("queries_per_day")
    s3_gb = g * total * store
    local_gb = g * local_days * store * (1 + over)
    store_src = ["input:tb_per_day", "coef:cartridge.files_bytes_per_raw", "coef:cartridge.field_data_bytes_per_raw"]

    build_name = sc.cartridge_build_instance
    build = ctx.instance(build_name)
    build_cores = g * (build_cs + side_cs) / SECONDS_PER_DAY / util
    build_nodes = max(1, ceil_pos(build_cores / build.vcpu))
    mb_s_per_node = GB_PER_TB * build.vcpu * util / (build_cs + side_cs) if build_cs + side_cs else math.inf

    query_name = sc.cartridge_query_instance
    qinst = ctx.instance(query_name)
    disk_max = ctx.rule("cartridge.node_disk_max_gb")
    by_disk = ceil_pos(local_gb / disk_max)
    query_nodes = max(sc.cartridge_query_nodes, by_disk)
    query_f = f"max(fixed fleet {sc.cartridge_query_nodes} (scenario assumption), ceil(local {local_gb:,.0f} GB / {disk_max:g} GB) = {by_disk})"
    puts_per_gb = ctx.coef("cartridge", "s3_put_per_stored_gb")
    gpq = sc.cartridge_gets_per_query
    return [
        line(ctx, sys, "build nodes", "ingest", build_nodes, "nodes", build.price_item, HOURS_PER_YEAR, "8760 h/yr",
             f"max(1, ceil({g:g} GB/day × ({build_cs:.4g} build + {side_cs:.4g} field data) core-s/GB / 86400 / {util:g} util / {build.vcpu} vCPU)) "
             f"(= {mb_s_per_node:.1f} MB/s raw per node)",
             ["input:tb_per_day", f"instance:{build_name}", "coef:cartridge.build_core_s_per_raw_gb", "input:target_cpu_utilization",
              "coef:cartridge.field_data_core_s_per_raw_gb"]),
        line(ctx, sys, "query nodes", "all", query_nodes, "nodes", qinst.price_item, HOURS_PER_YEAR, "8760 h/yr", query_f,
             [f"instance:{query_name}", *store_src, "input:cartridge_local_days", "input:cartridge_query_nodes", "sizing:cartridge.node_disk_max_gb"]),
        line(ctx, sys, "S3 storage (Cartridge files + field data, every tier)", "all", s3_gb, "GB", "aws.s3.standard.gb_month", MONTHS_PER_YEAR, "12 mo",
             f"{g:g} GB/day × {total:g} retained days × ({files:.4g} files + {side:.4g} field data)/raw",
             [*store_src, "input:hot_days", "input:warm_days", "input:frozen_days"]),
        line(ctx, sys, "EBS gp3 local copy", "hot", local_gb, "GB", "aws.ebs.gp3.gb_month", MONTHS_PER_YEAR, "12 mo",
             f"{g:g} GB/day × {local_days:g} local days × {store:.4g} stored/raw × (1+{over:g})",
             [*store_src, "input:cartridge_local_days", "input:cartridge_local_headroom"]),
        line(ctx, sys, "S3 PUT requests (upload)", "all", g * DAYS_PER_YEAR * store * puts_per_gb / 1000, "1k requests", "aws.s3.put_per_1k",
             1, "1 (already per year)", f"{g:g} GB/day × 365 × {store:.4g} stored/raw × {puts_per_gb:.4g} PUTs/GB / 1000",
             [*store_src, "coef:cartridge.s3_put_per_stored_gb"]),
        line(ctx, sys, "S3 GET requests", "all", qpd * DAYS_PER_YEAR * gpq / 1000, "1k requests", "aws.s3.get_per_1k", 1,
             "1 (already per year)", f"{qpd:g} q/day × 365 × {gpq:g} GETs per query (scenario assumption, every query) / 1000",
             ["input:queries_per_day", "input:cartridge_gets_per_query"]),
    ]


def elastic_serverless(ctx: Ctx) -> list[Row]:
    sys = "elastic_serverless"
    g = ctx.gb_per_day()
    total = ctx.inp("hot_days") + ctx.inp("warm_days") + ctx.inp("frozen_days")
    ret_src = ["input:tb_per_day", "input:hot_days", "input:warm_days", "input:frozen_days"]
    return [
        graduated_line(ctx, sys, "ingest", g * DAYS_PER_YEAR / MONTHS_PER_YEAR, "GB ingested", "elastic.serverless.ingest_per_gb",
                       f"{g:g} GB/day × 365 / 12", ["input:tb_per_day"]),
        graduated_line(ctx, sys, "retention", g * total, "GB retained", "elastic.serverless.retention_per_gb_month",
                       f"{g:g} GB/day × {total:g} retained days (steady state, billed on ingested GB)", ret_src),
    ]


def logsdb_variant(fn: Callable[..., list[Row]]) -> Callable[[Ctx], list[Row]]:
    def variant(ctx: Ctx) -> list[Row]:
        rows = fn(ctx, logsdb=True)
        for row in rows:
            row.sources.append(f"coef:elasticsearch.{LOGSDB_COEF}")
        return rows

    return variant


SYSTEM_FUNCS: dict[str, Callable[[Ctx], list[Row]]] = {
    "cartridge": cartridge,
    "es_self_managed": es_self_managed,
    "es_self_managed_enterprise_logsdb": logsdb_variant(es_self_managed),
    "elastic_serverless": elastic_serverless,
}


def line_items(inputs: Inputs, params: dict[str, float] | None = None, systems: list[str] | None = None) -> pd.DataFrame:
    ctx = Ctx(inputs, params if params is not None else build_params(inputs))
    systems = systems if systems is not None else list(SYSTEM_FUNCS)
    rows = [row for s in systems for row in SYSTEM_FUNCS[s](ctx)]
    return pd.DataFrame([asdict(r) | {"usd_year": r.usd_year} for r in rows])


def system_totals(inputs: Inputs, params: dict[str, float], systems: list[str]) -> dict[str, float]:
    """Yearly total per system without building the line-item table."""
    ctx = Ctx(inputs, params)
    return {s: sum(r.usd_year for r in SYSTEM_FUNCS[s](ctx)) for s in systems}
