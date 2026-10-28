# Cost model

Turns **measured stored sizes** into a **yearly AWS bill**.

- **Systems:** Cartridge, Elasticsearch, OpenSearch and Elastic Serverless.
- **Scale:** 10 TB of raw logs per day, 30 days searchable (plus 365-day and tiered variants).
- **Inputs:** every price, sizing rule and measured coefficient is a plain JSON file with its source next to it.
- **Arithmetic:** `src/cost_model/model.py`, one function per system.

```sh
cd cost
uv run pytest -q            # hand-computed formula tests + the cost page's headline figures
uv run cost-matrix          # every dataset x store config at 10 TB/day, 30 days  -> ../results/cost/matrix-10tb-30d.{md,json}
uv run cost-oneyear         # 30 vs 365 days, web server logs                      -> ../results/cost/oneyear-10tb-httplogs.{md,json}
uv run cost-tiered          # Elasticsearch tiered setups vs Cartridge, 5 datasets  -> ../results/cost/tiered-10tb-30d.{md,json}
uv run cost-lines scenarios/10tb-30d.yaml   # every priced line item with its formula -> ../results/cost/lines-10tb-30d.md
```

- Each command is deterministic: same files in, byte-identical tables out.
- The measured sizes it prices are listed in `src/cost_model/matrix.py` (`DATASETS`), each with the result file it came
  from under `../results/storage` or `../results/speed`.

## How a number is made

1. **Measure** (elsewhere in this repo): load the same raw data into each system on AWS and record the bytes it stores.
2. **Price** (here):
   - put the measured bytes-per-raw-byte into the model;
   - size each system by its vendor's rules;
   - multiply by AWS list prices.

Only the stored size changes from one dataset to the next. Build and search cost per GB are the web server log
(`http_logs`) measurements, reused for every dataset.

**Scenario for every headline figure:**

- 10 TB/day, 30 days searchable
- 1 replica for Elasticsearch/OpenSearch
- 100,000 searches a day each, over the last hour
- AWS us-east-2, on-demand list prices, October 2026

Dollar figures are model output, not invoices.

## Sizing rules

### Elasticsearch and OpenSearch (self-managed on EC2)

OpenSearch is priced by the same rules with its own measured size and no licence line.

| Step | Rule | Source |
|---|---|---|
| Instance | `i8g.4xlarge`: 16 vCPU, 128 GiB, 3,750 GB local NVMe (disk is in the instance price) | AWS EC2 |
| Copies | primary + 1 replica; the replica lives in another availability zone, so each replicated byte pays cross-zone transfer in both directions | Elastic shard-allocation-awareness docs |
| Disk needed | `raw GB/day × days × 2 copies × measured stored/raw ÷ 0.85` | 0.85 = Elasticsearch's default low disk watermark: a node past 85% full stops taking shards |
| Snapshot | frozen-tier data is held once in S3 at the measured snapshot size | Elastic frozen-tier docs |
| Nodes | `max(3, disk ÷ (RAM × 30), disk ÷ local NVMe, indexing cores ÷ vCPUs)`; warm tier uses RAM × 160, frozen RAM × 1500 | Elastic's log-cluster sizing guidance (1:30 hot, 1:160 warm, 1:1500 frozen) |
| Indexing cores | `raw GB/day × 584 core-s/GB × 2 copies ÷ 86,400 ÷ CPU target`; CPU target 1.0 | measured on `http_logs`, one r7i.4xlarge |
| Hours | 8,760 per year, on demand | |
| Replica traffic | `raw GB/day × 365 × replicas × 2 directions × $0.01` | AWS cross-zone price |
| Frozen cache | 10% of the S3 snapshot size on gp3, plus S3 GETs per search | Elastic frozen-tier docs |

Variants:

- **logsdb, free licence:** the measured logsdb size.
- **logsdb, Enterprise:** synthetic `_source`, which needs an Enterprise licence. Where not measured, Elastic's published retained fraction (39.4/162.7) is applied.
- **Frozen tier** (searchable snapshots): also needs Enterprise, so those setups carry the licence estimate below.

### Cartridge

| Step | Rule |
|---|---|
| Build servers | `ceil(raw GB/day × (build + field-data build core-s/GB) ÷ 86,400 ÷ CPU target ÷ vCPUs)`, `r7i.4xlarge`; 405 + 282 core-s/GB measured on `http_logs`; CPU target 1.0 |
| Query servers | **4 × `c7i.4xlarge`, a fixed fleet.** An assumption, not a measurement (see limits); raised only if the local copy would exceed one 64 TiB volume per node |
| S3 | one copy of all Cartridge files and field data, every retained day: `raw GB/day × days × (files + field data)/raw`; S3 keeps it across zones, so no replica and no replica traffic |
| Local copy | last 7 days on gp3, no free-space headroom: `raw GB/day × 7 × stored/raw` |
| S3 uploads | `raw GB/day × 365 × stored/raw × 119 PUTs per stored GB` (measured multipart parts) |
| S3 reads | **1,000 GETs per search, on every search**: `100,000 × 365 × 1,000` (an assumption) |

For datasets other than the web server logs no separate field-data build was run, so the matrix charges those
Cartridge rows no field-data bytes or build time.

## Price inputs

All in `data/prices.json` (one row each: unit, price, source URL, date accessed, notes). `data/price_map.json` is the
only link between the model and those rows; a mapped row that is missing or has no price stops the run.

| Item | Price | Source | Accessed |
|---|---:|---|---|
| EC2 `i8g.4xlarge` (Elasticsearch/OpenSearch nodes) | $1.3728/h | AWS public price list, us-east-2 (Ohio), Linux on-demand | 2026-10-23 |
| EC2 `i3en.3xlarge` (Elasticsearch warm nodes) | $1.356/h | same | 2026-10-23 |
| EC2 `r7i.4xlarge` (Cartridge build) | $1.0584/h | same | 2026-10-23 |
| EC2 `c7i.4xlarge` (Cartridge query) | $0.714/h | same | 2026-10-23 |
| EBS gp3 | $0.08/GB-month | AWS EBS price list | 2026-10-23 |
| S3 Standard storage | $0.023/GB-month | AWS S3 price list, first-50-TB rate used for every GB (higher than the volume tiers, so it overstates Cartridge and frozen-tier storage alike) | 2026-10-23 |
| S3 PUT/COPY/POST/LIST | $0.005 per 1,000 | AWS S3 price list | 2026-10-23 |
| S3 GET | $0.0004 per 1,000 | AWS S3 price list | 2026-10-23 |
| Cross-zone transfer | $0.01/GB each direction | AWS EC2 on-demand pricing page, "Data Transfer within the same AWS Region" | 2026-10-23 |
| Elastic Serverless, Observability "Logs Essentials" | graduated ingest and retention tiers (16 rows) | Elastic public price API, `cloud.elastic.co/api/v1/prices/base_prices` (SKUs `observability.logs-essentials-ingested_aws-us-east-2`, `...-retained_aws-us-east-2`), list | 2026-10-23 |
| Elasticsearch Enterprise subscription | $150K/yr per cluster, **estimate** | Vendr (`vendr.com/marketplace/elastic`, page dated February 2026): "Self-managed Enterprise subscriptions commonly start at $150,000+ annually and can exceed $500,000 for large-scale deployments." Elastic publishes no self-managed price. The $150,000 floor favours Elasticsearch. | 2026-10-24 |

**Elastic Serverless**

- Billed on gigabytes ingested and retained (measured before compression), so the dollar figure is the same for every dataset.
- 304,167 GB ingested a month and 300,000 GB-months retained gives $344,151 a year (about $344K).
- Logs Essentials is Elastic's cheapest published logs option, which favours Elastic.

**Other data files**

- Sizing rules and instance specs, with sources: `data/sizing.json`, `data/instances.json`.
- Measured coefficients, with derivation and source: `data/coefficients.json`.

## Scenarios

`scenarios/*.yaml`; every line is commented. All share the Cartridge side above and differ only in how Elasticsearch is run.

| File | Retention | Elasticsearch setup |
|---|---|---|
| `10tb-30d` | 30 days | all hot (the headline) |
| `10tb-30d-hotwarm` | 7 hot + 23 warm | hot/warm on the free licence: `i8g` hot nodes, `i3en.3xlarge` warm nodes, ILM |
| `10tb-30d-hotfrozen` | 7 hot + 23 frozen | Elastic's hot/frozen reference architecture; frozen tier needs Enterprise, licence estimate included |
| `10tb-365d`, `-hotwarm`, `-hotfrozen` | 365 days | the same three setups at one year (7 hot, the rest warm/frozen) |

## Known limits

The ways the comparison could be off, in both directions.

**Ways Elasticsearch may be shown as too expensive**

- *All 30 days on fast storage.* Node count is set by local disk. Keeping 1–3 days on fast nodes and the rest on warm
  or frozen tiers costs less: for web server logs the gap is about 10.5× with hot/warm on the free licence and about
  6.7× with hot/frozen on Enterprise (`cost-oneyear`, `cost-tiered`).
- *Conservative RAM ratio.* 1:30 is Elastic's figure for hot nodes; log clusters often run leaner. Together with network
  storage instead of local NVMe that could roughly halve the Elasticsearch bill.
- *List prices.* Reserved instances or savings plans cut both bills by 30–40%; the multiples hold, the dollar savings shrink.

**Ways Cartridge may be shown as too cheap**

- *Query fleet not load-tested.* The 4 query servers have not been tested at 100,000 searches a day.
- *Older data is slower.* Elasticsearch serves all 30 days from local disk; Cartridge keeps 7 days local and reads the
  rest from S3, so first searches of older data take longer.
- *No headroom.* Both sides are sized at 100% CPU. At 60% utilisation Cartridge's build fleet would need about 9 servers
  instead of 5 (about $37K a year more); Elasticsearch's count is set by disk, so the same change costs it nothing.
- *Build cost measured on one dataset.* Build and search cost per GB come from the web server logs and are reused; the
  traces build measured about 495 core-s/GB against the 405 used.
- *Not every feature.* The comparison assumes both systems answer the same questions; Elasticsearch is stronger at sums,
  percentiles and grouping on fields with many distinct values.

**Ways Elasticsearch may be shown as too cheap**

- *Serverless is priced at its cheapest logs tier.* Teams that need the full Observability feature set pay more.
- *Vendor sizing guidance is stricter.* AWS's OpenSearch sizing guide uses storage = source × (1 + replicas) × 1.45
  (this model: ÷ 0.85) and, for heavy workloads, 2 vCPU and 8 GiB per 100 GiB of storage. The Elasticsearch and
  OpenSearch figures here are on the low side of what the vendors' own guidance implies.
- *Enterprise licence at the market floor.* Elastic prices by memory; a real quote for this cluster would likely be higher.

**Ways the measurements could be noisy**

- One run each, on samples of 2.4 to 23 GB, scaled to 10 TB/day.
- Mappings differ between systems: OpenSearch used explicit mappings and Elasticsearch its stock templates or dynamic
  mapping, so the two standard-mode columns are not like-for-like on the database logs.
- Elastic's 76% logsdb reduction and OpenSearch's measured ratio come from 1× `http_logs` runs and are assumed to hold at scale.

**Left out entirely** (most would favour Cartridge if included): staff time to run the cluster, Elasticsearch master
nodes and dashboards, backups of the hot tier, and the cost of shipping logs into either system.

## Layout

```
cost/
  pyproject.toml            uv project; console scripts cost-matrix / cost-oneyear / cost-tiered / cost-lines
  data/                     prices.json, price_map.json, coefficients.json, sizing.json, instances.json
  scenarios/                six scenario files (above)
  src/cost_model/           schema.py, load.py (validated reads), model.py (the arithmetic), matrix.py, oneyear.py, tiered.py, lines.py
  tests/                    hand-computed formula tests and the published-figures check
```
