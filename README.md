# Cartridge benchmarks

**At a glance**

- **Storage:** Cartridge stores five public log datasets in 7–19% of their raw size, **1.8x to 12.6x smaller** than Elasticsearch (logsdb and standard).
- **Speed:** hot searches on web logs take the same time as Elasticsearch. With the data in S3, Cartridge returns its first answer in **9–10 s, against 30–71 s**.
- **Cost:** at 10 TB of logs a day with 30 days searchable, web logs cost **$105K a year with Cartridge, against $1.10M–$1.96M** for the others.

![Yearly cost at 10 TB a day, 30 days searchable, per dataset and system](plots/cost.svg)

**How the numbers were made**

- Public datasets, run on AWS.
- Every system runs in its documented default setup. Mappings and templates are in the repo.
- Each number is one measurement. Nothing was re-run to pick a better value.
- Caveats sit directly under the numbers they apply to.
- Each section ends with the script that produced its numbers and the stored result they came from.
- Charts are drawn from the stored results by [`plots/make_plots.py`](plots/make_plots.py).

## Storage

![Stored size as a fraction of raw size, per dataset and system](plots/storage.svg)

Stored size, with how many times larger than Cartridge in brackets. All sizes are measured the same way: one shard, no replica, force-merged to one segment, primary store bytes.

| Dataset | Raw | Cartridge | ES logsdb | ES standard | OpenSearch |
|---|---:|---:|---:|---:|---:|
| Web logs | 23.5 GB | **2.98 GB** | 10.6 GB (3.5x) | 18.7–22.5 GB (6.3–7.6x) | 19.5 GB (6.5x) |
| Thunderbird | 10.7 GB | **0.70 GB** | 2.40 GB (3.4x) | 7.42 GB (10.6x) | 7.61 GB (10.9x) |
| CockroachDB | 10.5 GB | **0.77 GB** | 1.51 GB (2.0x) | 9.68 GB (12.6x) | 3.75 GB (4.9x) |
| CloudTrail | 2.4 GB | **0.46 GB** | 0.84 GB (1.8x) † | 1.44 GB (3.2x) | 1.48 GB (3.2x) |
| Traces | 19.7 GB | **1.57 GB** | 4.56 GB (2.9x) | 5.20 GB (3.3x) | 9.47 GB (6.0x) |

ES = Elasticsearch. Exact byte counts are in the result files linked below.

**What it shows**

- The biggest gaps are against Elasticsearch standard: 10.6x on Thunderbird and 12.6x on CockroachDB.
- The smallest gap is on traces: 3.3x against standard, 2.9x against logsdb.
- Against logsdb the gaps range from 1.8x (CloudTrail) to 3.5x (web logs).

**Notes**

- **Cartridge level.** Ratios use Cartridge at level 2, the default press. Thunderbird, CockroachDB, CloudTrail and traces also have a level 1 press, which is smaller; see the dataset READMEs.
- **Web logs.** Cartridge is a 2.12 GB cartridge plus a 0.86 GB field index (12.7% of raw), default press flags. Elasticsearch standard was measured twice by the same method and gave two different sizes; the cause is not known.
- **logsdb.** Uses the free licence. On traces, the logsdb column is the stock trace stream.
- **† CloudTrail.** The logsdb column is Elastic's stock logs data stream, which leaves 20.9% of events partly unsearchable. A fully searchable variant with four flattened fields is 997 MB (41.7% of raw, 2.2x Cartridge). Elasticsearch standard uses the same four flattened fields.
- **CockroachDB.** Elasticsearch used dynamic mapping; OpenSearch used an explicit timestamp mapping.

**Script → Result**

| Dataset | Script | Result |
|---|---|---|
| Web logs | [`speed/http_logs/10-size.sh`](speed/http_logs/10-size.sh) | [`results/speed/http_logs/size/`](results/speed/http_logs/size) (Cartridge: [`verify/`](results/speed/http_logs/verify)) |
| Thunderbird | [`storage/thunderbird/run.sh`](storage/thunderbird/run.sh) | [`thunderbird-es955-cartridge.md`](results/storage/thunderbird-es955-cartridge.md) |
| CockroachDB | [`storage/cockroachdb/run.sh`](storage/cockroachdb/run.sh) | [`cockroachdb-es955-cartridge.md`](results/storage/cockroachdb-es955-cartridge.md) |
| CloudTrail | [`storage/cloudtrail/run.sh`](storage/cloudtrail/run.sh) | [`cloudtrail-es955-cartridge.md`](results/storage/cloudtrail-es955-cartridge.md) |
| Traces | [`storage/traces/run.sh`](storage/traces/run.sh) | [`traces-es955-cartridge.md`](results/storage/traces-es955-cartridge.md) |

## Speed

![Web-log search time per tier, Cartridge against Elasticsearch](plots/speed.svg)

Web logs: total time for the full set of 39 searches.

| Tier | Where the data is | Cartridge | Elasticsearch |
|---|---|---:|---:|
| Hot | Local disk | **11.0 s** | 11.5 s |
| Warm, first answer | S3, fresh server | **9–10 s** | 30–71 s |
| Warm, all 39 | Local, after first fetch | 9.9 s | **9.6 s** |
| Cold | Stays in S3 | **63 s** \* | 290 s \* |

\* The cold row counts only the 35 searches both systems answer.

**Notes**

- **Hot.** Cartridge's 11.0 s uses its field index. Without it the run takes 16.3 s.
- **Warm.** Elasticsearch's first answer takes 30–47 s with a fully mounted searchable snapshot, and 64–71 s with a restore to local disk.
- **Cold.** Elasticsearch uses the frozen tier. On some chains, cold Cartridge searches do not finish within 60 s. A fix is in progress, so the 63 s will change.

**Script → Result**

- Script: [`speed/http_logs/20-speed.sh`](speed/http_logs/20-speed.sh), arms `hot-cart`, `hot-es`, `warm-cart`, `warm-es-fullcopy`, `warm-es-restore`, `cold-cart`, `cold-es`
- Result: [`results/speed/http_logs/speed/`](results/speed/http_logs/speed)

| Run | Log |
|---|---|
| Hot | `hot-cart-field-index.log`, `hot-cart-no-field-index.log`, `hot-es.log` |
| Warm | `warm-cart-field-index.log`, `warm-es-fullcopy.log`, `warm-es-restore.log` |
| Cold | `cold-cart.log`, `cold-es-frozen.log` |

## Correctness

| Hot-run searches with the exact answer | Cartridge | Elasticsearch |
|---|---:|---:|
| Out of 39 | **39** | 34 |

- **Elasticsearch's five misses** are top-N searches at its default setting.
- **Independent check.** 48 of 48 searches match answers computed independently from the raw text (run on 2026-10-26).

**Script → Result:** [`speed/http_logs/reference.py`](speed/http_logs/reference.py), [`verify_cart.py`](speed/http_logs/verify_cart.py) → [`results/speed/http_logs/verify/`](results/speed/http_logs/verify)

## Cost

Yearly cost for web logs at 10 TB a day, 30 days searchable. This is model output at AWS us-east-2 list prices (October 2026), not an invoice. It prices the sizes measured above. The chart at the top shows all five datasets.

| | Cartridge | ES logsdb | ES standard | OpenSearch |
|---|---:|---:|---:|---:|
| Per year | **$105K** | $1.10M | $1.88M | $1.96M |
| vs Cartridge | 1.0x | 10.4x | 17.8x | 18.6x |

**Other datasets:** Elasticsearch standard costs 8.5x to 27.6x as much as Cartridge, and logsdb 5.1x to 9.1x.

**Notes**

- **Conservative ratios.** Ratios divide by the larger of the two Cartridge sizes for each dataset. The full table also has the smaller size.
- **Web-log size priced.** The verified default press: 2.12 GB cartridge plus 0.86 GB field index (2.98 GB in total).
- **CloudTrail logsdb.** The bar is the stock logs stream at $879K a year, marked † in the chart. The flattened variant is $1.02M (10.6x).
- **Licences.** logsdb uses the free licence. Elasticsearch's Enterprise-licence setups (synthetic source, frozen tier) are priced only where the table says so.

**Script → Result:** [`cost/`](cost) (`cd cost && uv run cost-matrix`) → [`results/cost/matrix-10tb-30d.md`](results/cost/matrix-10tb-30d.md), [`matrix-10tb-30d.json`](results/cost/matrix-10tb-30d.json)

## Reproduced

To check that the public scripts alone give the published numbers:

- `storage/cloudtrail/run.sh` was run unmodified
- from a clean `git archive` of this repository (commit `0207790`)
- on a fresh c7i.4xlarge, on 2026-10-26.

| System | Committed | Reproduced | Difference |
|---|---:|---:|---:|
| ES standard (flattened fields) | 1,439 MB | 1,439 MB | +0.040% |
| ES logsdb (flattened fields) | 997 MB | 997 MB | −0.006% |
| ES stock logs data stream | 842 MB | 842 MB | +0.001% |
| OpenSearch 3.9.0 default | 1,476 MB | 1,476 MB | −0.008% |
| Cartridge level 2 | 456 MB | 456 MB | −18 bytes |
| Cartridge level 1 | 389 MB | 389 MB | −18 bytes |

- **Cartridge's 18 bytes.** The reproduction used a newer build (cartpress 0.17.1, build `513456b75`) than the committed run (build `6bbd7038c`).
- **Elasticsearch and OpenSearch** sizes vary slightly between runs.
- **Why the log ends in FAILED.** At the time, the checking script required byte-identical Cartridge sizes across builds and compared OpenSearch with the wrong reference figure. Both were fixed afterwards; the table uses the corrected comparison.

**Script → Result:** [`storage/cloudtrail/run.sh`](storage/cloudtrail/run.sh) → [`results/repro/cloudtrail-c7i-4xlarge-2026-10-26.log`](results/repro/cloudtrail-c7i-4xlarge-2026-10-26.log)

## Layout

| Directory | What it holds |
|---|---|
| [`storage/`](storage) | One directory per dataset: `run.sh`, its loaders, the OpenSearch mapping, and a README. Index: [`storage/README.md`](storage/README.md). |
| [`speed/`](speed) | The web-log benchmark ([`speed/http_logs`](speed/http_logs)): download, size passes, speed tiers, the 39 searches with expected answers, and the correctness check. |
| [`cost/`](cost) | The cost model: prices, sizing rules and measured coefficients as sourced JSON, plus one arithmetic function per system. |
| [`results/`](results) | The logs and tables the scripts produced. Every number in the READMEs is in a file here. |
| [`plots/`](plots) | `make_plots.py` and the SVG charts it draws from `results/`. |
| [`lib/`](lib), `speed/lib/` | Shared helpers: Docker containers, bulk loading, downloads and checksums, force-merge and settle measurement, the results table, the search runner. The commands that decide a number stay in `run.sh` and `20-speed.sh`. |

## How to run

**What you need**

- An AWS account.
- A Linux machine with Docker (run through `sudo`), `curl`, `jq`, `python3` and `uv`. The scripts download tens of gigabytes and take hours, so they are not meant for a laptop.
- For the web-log speed runs: an S3 bucket (`export BUCKET=...`) and an instance role that can read and write it.
- Per-dataset needs are in each script's header.

**Machines we used** (on demand)

| Work | Instance |
|---|---|
| Loading, pressing, size measurements | r7i.4xlarge (16 vCPU, 128 GB) |
| Web-log speed runs | c7i.4xlarge (16 vCPU, 32 GiB, gp3 at 16,000 IOPS) |

**Datasets**

| Dataset | Source | Fetched by |
|---|---|---|
| Web logs (1998 World Cup) | Rally track `http_logs`, `https://rally-tracks.elastic.co/http_logs` | `speed/http_logs/00-data.sh` |
| Thunderbird syslog | Loghub, Zenodo record 8196385 (CC-BY 4.0) | `storage/thunderbird/run.sh` |
| CockroachDB JSON logs | Zenodo record 10516387 (CC-BY 4.0) | `storage/cockroachdb/run.sh` |
| CloudTrail logs | flaws.cloud, `summitroute.com/downloads/flaws_cloudtrail_logs.tar` | `storage/cloudtrail/run.sh` |
| Microservice traces | Alibaba cluster-trace-microservices-v2022, call-graph chunks 0 to 3 | `storage/traces/run.sh` |

**Commands**

```sh
# storage: one dataset at a time
storage/thunderbird/run.sh     # likewise cockroachdb, cloudtrail, traces

# web logs
export BUCKET=<your-s3-bucket>
speed/http_logs/00-data.sh                # download, check sizes, line count and three reference counts
speed/http_logs/10-size.sh all            # stored sizes
speed/http_logs/20-speed.sh setup         # load Elasticsearch, snapshot, press Cartridge, upload
speed/http_logs/20-speed.sh all           # hot, warm and cold arms
# correctness check: see speed/http_logs/README.md ("How exactness was checked")

# cost: needs only the stored results
cd cost && uv run cost-matrix

# charts: redraw plots/*.svg from results/
uv run --script plots/make_plots.py
```

**Getting Cartridge**

- Install: `curl -sSf https://cartridge.app/install | sh` installs `cartridge` and `cartpress`, or download them from [cartridge.app](https://cartridge.app).
- A press uses your account's pressing credit (the first 25 GB are free) and asks you to confirm.
- The stored runs used the same release built without the licence check, so they drew no pressing credit. A press with the public command can give slightly different sizes (see [`speed/http_logs/README.md`](speed/http_logs/README.md)).

## Fairness

- **Defaults for every system.**
  - Elasticsearch 9.5.x in Docker, one node, free licence, security off.
  - Standard mode is `index.mode=standard` with dynamic mapping, apart from the fields named in each README. logsdb is the stock data stream or template.
  - OpenSearch 3.9.0 has every storage setting at its default.
  - Mappings and templates: [`es-index-template.json`](speed/http_logs/es-index-template.json) (web logs) and the OpenSearch mappings for [thunderbird](storage/thunderbird/opensearch-mapping.json), [cockroachdb](storage/cockroachdb/opensearch-mapping.json), [cloudtrail](storage/cloudtrail/opensearch-mapping.json) and [traces](storage/traces/opensearch-mapping.json).
- **One measurement per number.** Each size, time and cost comes from one stored run. Nothing was repeated to find a better value. Where a first pass was thrown away, the README says why.
- **Sizes measured the same way.** One shard, no replica, force-merge to one segment, then primary store bytes. For OpenSearch the measurement also flushes and waits for the size to settle.
- **Same limits for speed runs.**
  - Both systems run in Docker with 4 CPUs and 16 GB, on the same instance type, volume and bucket.
  - Result caches are off. The file cache is dropped and the server restarted before each chain.
  - Each search is capped at 60 s.
- **Where Cartridge does not win.**
  - Elasticsearch loads the traces data faster than Cartridge presses it.
  - The size gap on traces is the smallest of the five.
  - The cold row counts only the 35 searches both systems answer.
- **Details:** [`speed/http_logs`](speed/http_logs/README.md) · [`storage`](storage/README.md) · [`thunderbird`](storage/thunderbird/README.md) · [`cockroachdb`](storage/cockroachdb/README.md) · [`cloudtrail`](storage/cloudtrail/README.md) · [`traces`](storage/traces/README.md) · [`cost`](cost/README.md)
