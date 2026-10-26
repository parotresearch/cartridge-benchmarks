# Cartridge benchmarks

This repository reproduces our published comparison of Cartridge with Elasticsearch (standard and logsdb) and OpenSearch: how many bytes each stores,
how fast each answers a set of investigation searches, and what that costs per year at 10 TB of logs a day. Everything uses public datasets and runs on AWS.
Each number below links to the script that produced it and to the stored log or table it came from. Every system is run in its documented default setup
(mappings and templates are in the repo), each number is one measurement that was not re-run to pick a better one, and the known caveats are written next to the numbers.

## Claims, scripts and results

| # | Claim | Script | Result |
|---|---|---|---|
| 1 | **Web logs (1998 World Cup, 23.5 GB), stored size.** Elasticsearch standard 18,656,019,625 to 22,547,013,768 B (two runs, same method; cause of the gap not known); Elasticsearch logsdb (free licence) 10,567,779,983 B; OpenSearch 19,456,920,952 B; Cartridge 2,978,277,499 B, default press flags, field index included (2,118,597,954 B cartridge + 859,679,545 B field index; 0.127x raw). Cartridge is 6.3x to 7.6x smaller than Elasticsearch standard, 3.5x smaller than logsdb and 6.5x smaller than OpenSearch | [`speed/http_logs/10-size.sh`](speed/http_logs/10-size.sh) (other systems); the Cartridge figure is from the verify run | [`results/speed/http_logs/size/`](results/speed/http_logs/size); Cartridge: [`results/speed/http_logs/verify/`](results/speed/http_logs/verify) |
| 2 | **Thunderbird syslog (10.7 GB), stored size.** Elasticsearch standard 7,419,489,100 B; logsdb 2,400,695,754 B; OpenSearch 7,614,836,272 B; Cartridge 701,303,359 B. 10.6x smaller than standard, 3.4x smaller than logsdb | [`storage/thunderbird/run.sh`](storage/thunderbird/run.sh) | [`results/storage/thunderbird-es955-cartridge.md`](results/storage/thunderbird-es955-cartridge.md) |
| 3 | **CockroachDB JSON logs (10.5 GB), stored size.** Elasticsearch standard 9,682,259,352 B; logsdb 1,506,138,614 B; OpenSearch 3,751,271,057 B; Cartridge 766,850,694 B. 12.6x smaller than standard, 2.0x smaller than logsdb | [`storage/cockroachdb/run.sh`](storage/cockroachdb/run.sh) | [`results/storage/cockroachdb-es955-cartridge.md`](results/storage/cockroachdb-es955-cartridge.md) |
| 4 | **CloudTrail audit logs (2.4 GB), stored size.** Elasticsearch standard with four flattened fields 1,438,882,886 B; logsdb 996,991,992 B; stock logs stream 841,790,533 B (20.9% of events partly unsearchable); OpenSearch 1,476,093,976 B; Cartridge 456,060,724 B. 3.2x smaller than standard, 2.2x smaller than logsdb | [`storage/cloudtrail/run.sh`](storage/cloudtrail/run.sh) | [`results/storage/cloudtrail-es955-cartridge.md`](results/storage/cloudtrail-es955-cartridge.md) |
| 5 | **Microservice traces as OpenTelemetry spans (19.7 GB), stored size.** Elasticsearch standard 5,200,242,650 B; stock trace stream (logsdb) 4,560,877,302 B; OpenSearch 9,471,101,499 B; Cartridge 1,568,758,212 B. 3.3x smaller than standard, 2.9x smaller than logsdb (the smallest gap of the five datasets) | [`storage/traces/run.sh`](storage/traces/run.sh) | [`results/storage/traces-es955-cartridge.md`](results/storage/traces-es955-cartridge.md) |
| 6 | **Web logs, hot** (data on local disk, 39 searches): Cartridge 11.0 s, Elasticsearch 11.5 s. Cartridge's 11.0 s uses its field index; without it the run takes 16.3 s | [`speed/http_logs/20-speed.sh`](speed/http_logs/20-speed.sh) (`hot-cart`, `hot-es`) | [`results/speed/http_logs/speed/`](results/speed/http_logs/speed) `hot-cart-field-index.log`, `hot-es.log`, `hot-cart-no-field-index.log` |
| 7 | **Web logs, warm** (data in S3, fresh server): first answer in 9 to 10 s for Cartridge, 30 to 71 s for Elasticsearch (30 to 47 s with a fully mounted searchable snapshot, 64 to 71 s with a restore to local disk) | `20-speed.sh` (`warm-cart`, `warm-es-fullcopy`, `warm-es-restore`) | `warm-cart-field-index.log`, `warm-es-fullcopy.log`, `warm-es-restore.log` in the same directory |
| 8 | **Web logs, cold** (data stays in S3), the 35 searches both systems answer: Cartridge 63 s, Elasticsearch (frozen tier) 290 s. A fix for Cartridge's cold time is in progress, so the 63 s will change | `20-speed.sh` (`cold-cart`, `cold-es`) | `cold-cart.log`, `cold-es-frozen.log` in the same directory |
| 9 | **Answers are correct.** 48 of 48 searches match answers computed independently from the raw text (run on 2026-10-26); in the hot run Cartridge's answers are exact on 39 of 39 searches and Elasticsearch's on 34 of 39 (the other five are top-N searches at Elasticsearch's default setting) | [`speed/http_logs/reference.py`](speed/http_logs/reference.py), [`verify_cart.py`](speed/http_logs/verify_cart.py) | [`results/speed/http_logs/verify/`](results/speed/http_logs/verify) |
| 10 | **Yearly cost at 10 TB a day, 30 days searchable** (model output, AWS us-east-2 list prices, October 2026). Cartridge $112,538 on web logs against $1,876,859 (Elasticsearch standard, 16.7x), $1,095,187 (logsdb free licence, 9.7x) and $1,961,039 (OpenSearch, 17.4x). Across the other four datasets Elasticsearch standard costs 8.5x to 27.6x as much, logsdb (free licence) 5.1x to 10.6x | [`cost/`](cost) (`uv run cost-matrix`) | [`results/cost/matrix-10tb-30d.md`](results/cost/matrix-10tb-30d.md) |

Ratios are stored bytes divided by Cartridge's bytes (level 2, the default press). Rows 2 to 5 also have a level 1 press, which is smaller; see the dataset READMEs.
Row 10 divides by the larger of the two Cartridge sizes per dataset, so it is the conservative ratio; the table also has the smaller one.

## Reproduced

To check that the public scripts alone give the published numbers, `storage/cloudtrail/run.sh` was run unmodified from a clean `git archive` of this repository (commit `0207790`)
on a fresh c7i.4xlarge on 2026-10-26. Log: [`results/repro/cloudtrail-c7i-4xlarge-2026-10-26.log`](results/repro/cloudtrail-c7i-4xlarge-2026-10-26.log).

| System | Committed bytes | Reproduced bytes | Difference |
|---|---:|---:|---:|
| Elasticsearch standard (flattened fields) | 1,438,882,886 | 1,439,455,684 | +0.040% |
| Elasticsearch logsdb (flattened fields) | 996,991,992 | 996,928,985 | -0.006% |
| Elasticsearch stock logs data stream | 841,790,533 | 841,798,533 | +0.001% |
| OpenSearch 3.9.0 default | 1,476,093,976 | 1,475,979,582 | -0.008% |
| Cartridge level 2 | 456,060,724 | 456,060,706 | -18 B |
| Cartridge level 1 | 389,109,483 | 389,109,465 | -18 B |

Cartridge differs by 18 bytes at both levels because the reproduction used a newer build (cartpress 0.17.1, build `513456b75`) than the committed run (build `6bbd7038c`).
Elasticsearch and OpenSearch sizes vary slightly between runs. The log's last line says FAILED because the checking script then required byte-identical Cartridge sizes across builds and
compared OpenSearch with the wrong reference figure; both were fixed afterwards and the table above uses the corrected comparison.

## Layout

| Directory | What it holds |
|---|---|
| [`storage/`](storage) | One directory per dataset (`thunderbird`, `cockroachdb`, `cloudtrail`, `traces`): a `run.sh` with the commands that produce each size, the loaders and converters it calls, the OpenSearch mapping, and a README with the stored results and caveats. [`storage/README.md`](storage/README.md) is the index. |
| [`speed/`](speed) | The web-log benchmark ([`speed/http_logs`](speed/http_logs)): data download, size passes, the speed tiers, the 39 searches with their expected answers, and the correctness check. |
| [`cost/`](cost) | The cost model. Prices, sizing rules and measured coefficients are plain JSON files with their sources; the arithmetic is one function per system. It prices the sizes measured in `storage/` and `speed/`. |
| [`results/`](results) | The logs and tables the scripts produced: `storage/`, `speed/http_logs/` and `cost/`. Every number in the READMEs is in a file here. |
| [`lib/`](lib), `speed/lib/` | The boilerplate the scripts share, kept out of the way: starting and waiting for the Docker containers, bulk-loading, download and checksum helpers, the force-merge, flush and settle measurement, the results table, the search runner. The commands that decide a number stay in the `run.sh` and `20-speed.sh` files. |

## How to run

You need an AWS account and a Linux machine with Docker (run through `sudo`), `curl`, `jq`, `python3` and `uv`. The scripts start containers, download tens of gigabytes and take hours;
they are not meant for a laptop. We used one r7i.4xlarge (16 vCPU, 128 GB) on demand for loading, pressing and the size measurements, and a c7i.4xlarge (16 vCPU, 32 GiB, gp3 at 16,000 IOPS)
for the web-log speed runs. The speed runs also need an S3 bucket (`export BUCKET=...`) and an instance role that can read and write it. Per-dataset needs are in each script's header.

Datasets, each downloaded and checked by the script that uses it:

| Dataset | Source | Fetched by |
|---|---|---|
| Web logs (1998 World Cup) | Rally track `http_logs`, `https://rally-tracks.elastic.co/http_logs` | `speed/http_logs/00-data.sh` |
| Thunderbird syslog | Loghub, Zenodo record 8196385 (CC-BY 4.0) | `storage/thunderbird/run.sh` |
| CockroachDB JSON logs | Zenodo record 10516387 (CC-BY 4.0) | `storage/cockroachdb/run.sh` |
| CloudTrail logs | flaws.cloud, `summitroute.com/downloads/flaws_cloudtrail_logs.tar` | `storage/cloudtrail/run.sh` |
| Microservice traces | Alibaba cluster-trace-microservices-v2022, call-graph chunks 0 to 3 | `storage/traces/run.sh` |

Order:

```sh
# storage: one dataset at a time
storage/thunderbird/run.sh     # likewise cockroachdb, cloudtrail, traces

# web logs
export BUCKET=<your-s3-bucket>
speed/http_logs/00-data.sh                # download, check sizes, line count and three reference counts
speed/http_logs/10-size.sh all            # stored sizes
speed/http_logs/20-speed.sh setup         # load Elasticsearch, snapshot, press Cartridge, upload
speed/http_logs/20-speed.sh all           # hot, warm and cold arms
# correctness check against answers computed from the raw text: see speed/http_logs/README.md ("How exactness was checked")

# cost: needs only the stored results
cd cost && uv run cost-matrix
```

Cartridge: `curl -sSf https://cartridge.app/install | sh` installs `cartridge` and `cartpress`. A press uses your account's pressing credit (the first 25 GB are free) and asks you to confirm.
The stored runs used a keyless benchmark build of the same release, so a press with the public command can give slightly different sizes (see [`speed/http_logs/README.md`](speed/http_logs/README.md)).

## Fairness

- **Defaults for every system.** Elasticsearch 9.5.x in Docker, one node, free licence, security off. Standard mode is `index.mode=standard` with dynamic mapping apart from the fields named in each README; logsdb is the stock data stream or template.
  OpenSearch 3.9.0 has every storage setting at its default. Mappings and templates: [`speed/http_logs/es-index-template.json`](speed/http_logs/es-index-template.json),
  [`storage/thunderbird/opensearch-mapping.json`](storage/thunderbird/opensearch-mapping.json), [`storage/cockroachdb/opensearch-mapping.json`](storage/cockroachdb/opensearch-mapping.json),
  [`storage/cloudtrail/opensearch-mapping.json`](storage/cloudtrail/opensearch-mapping.json), [`storage/traces/opensearch-mapping.json`](storage/traces/opensearch-mapping.json).
  Elasticsearch's Enterprise-licence setups (synthetic source, frozen tier) are priced or measured only where the results file says so.
- **One measurement per number.** Each size, time and cost comes from one stored run. Nothing was repeated to find a better value; where a first pass was thrown away, the README says why.
- **Sizes are measured the same way.** One shard, no replica, force-merge to one segment, then primary store bytes. For OpenSearch the measurement also flushes and waits for the size to settle.
- **Same limits for speed runs.** Both systems run in Docker with 4 CPUs and 16 GB, the same instance type, volume and bucket. Result caches are off, the file cache is dropped and the server restarted before each chain, and each search is capped at 60 s.
- **Where Cartridge does not win.** Elasticsearch loads the traces data faster than Cartridge presses it, and the size gap on traces is the smallest. Cold Cartridge searches on some chains do not finish in 60 s, and the cold row only counts the 35 searches both systems answer.
  CloudTrail's stock Elasticsearch setup leaves 20.9% of events partly unsearchable; the fully searchable setups are larger.
- **Known caveats.** CockroachDB: Elasticsearch used dynamic mapping where OpenSearch used an explicit timestamp mapping.
  Web logs: two Elasticsearch standard sizes were measured (22.5 GB and 18.7 GB) and the cause of the difference is not recorded. The cost figures are model output at list prices, not invoices.
  Details: [`speed/http_logs/README.md`](speed/http_logs/README.md), [`storage/README.md`](storage/README.md), [`storage/thunderbird`](storage/thunderbird/README.md), [`storage/cockroachdb`](storage/cockroachdb/README.md),
  [`storage/cloudtrail`](storage/cloudtrail/README.md), [`storage/traces`](storage/traces/README.md), [`cost/README.md`](cost/README.md).
