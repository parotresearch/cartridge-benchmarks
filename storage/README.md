# Storage benchmarks

How many bytes four real datasets take once stored in Elasticsearch 9.5.5 (standard and logsdb), OpenSearch 3.9.0 (default settings) and Cartridge.
Each dataset has a `run.sh` that downloads the public data and runs every step as a visible command, a README with the stored results and fairness notes,
and the loaders and mappings it uses. Shared helpers are in [`../lib`](../lib). Stored results and logs are in [`../results/storage`](../results/storage).

All sizes are primary store bytes: one shard, no replica, after a force-merge to one segment.
Hardware for the runs: one AWS r7i.4xlarge (16 vCPU, 128 GB), on demand, no other load (the Elasticsearch and Cartridge sizes for Thunderbird, CockroachDB and CloudTrail were measured on a c7i.4xlarge with 30 GB; see each README).

| dataset | raw bytes | Elasticsearch standard | Elasticsearch logsdb | OpenSearch default | Cartridge level 2 | Cartridge level 1 |
|---|---:|---:|---:|---:|---:|---:|
| [Thunderbird syslog](thunderbird/README.md) | 10,737,418,238 | 7,419,489,100 | 2,400,695,754 | 7,614,836,272 | 701,303,359 | 525,666,845 |
| [CockroachDB JSON logs](cockroachdb/README.md) | 10,506,623,721 | 9,682,259,352 | 1,506,138,614 | 3,751,271,057 | 766,850,694 | 557,402,533 |
| [CloudTrail (flaws.cloud)](cloudtrail/README.md) | 2,389,223,172 | 1,438,882,886 | 996,991,992 (flattened) / 841,790,533 (stock stream, 20.9% of events partly unsearchable) | 1,476,093,976 | 456,060,724 | 389,109,483 |
| [Alibaba traces as OTel spans](traces/README.md) | 19,744,374,361 | 5,200,242,650 | 4,560,877,302 | 9,471,101,499 | 1,568,758,212 | 1,048,451,721 |

Sources, in the order of the columns:

| dataset | Elasticsearch and Cartridge | OpenSearch |
|---|---|---|
| Thunderbird | [thunderbird-es955-cartridge.md](../results/storage/thunderbird-es955-cartridge.md) | [opensearch log](../results/storage/opensearch-default-real-r7i-4xlarge-2026-10-26.log) |
| CockroachDB | [cockroachdb-es955-cartridge.md](../results/storage/cockroachdb-es955-cartridge.md) | [opensearch log](../results/storage/opensearch-default-real-r7i-4xlarge-2026-10-26.log) |
| CloudTrail | [cloudtrail-es955-cartridge.md](../results/storage/cloudtrail-es955-cartridge.md) | [opensearch log, flush rerun](../results/storage/opensearch-default-real-r7i-4xlarge-2026-10-26-flush.log) |
| Traces | [traces-es955-cartridge.md](../results/storage/traces-es955-cartridge.md) | [opensearch log, flush rerun](../results/storage/opensearch-default-real-r7i-4xlarge-2026-10-26-flush.log) |

## Reading the table
- The "Elasticsearch standard" column is Elasticsearch in `index.mode=standard`. CloudTrail needs four fields mapped `flattened` to be searchable at all; the default dynamic mapping hits the 1,000-field limit and rejects 79.1% of events.
- Elasticsearch logsdb (free licence) stores `_source` as is. A paid licence can synthesise it; that setup was not measured here.
- CockroachDB: Elasticsearch standard used dynamic mapping; OpenSearch uses an explicit `@timestamp` mapping with the rest dynamic.
- Cartridge CockroachDB numbers are from the native `--gron` press; an earlier pipe-fed run was 5.7% / 8% smaller because it reordered records, and is not used.
- OpenSearch Thunderbird and CockroachDB: an earlier refresh-only measurement was 7,388,032,630 and 3,722,426,390 B; the flush and settle step made no material difference (+3.1% / +0.8%).

## Running
```
storage/<dataset>/run.sh          # thunderbird, cockroachdb, cloudtrail or traces
```
Needs a Linux box with Docker (run through `sudo`), `curl`, `jq`, `python3`, `uv` (and `gron` for CloudTrail), 150 to 250 GB of free disk and several hours.
The Cartridge step installs the public CLI with `curl -sSf https://cartridge.app/install | sh` and runs `cartpress press`. A press uses your pressing credit (25 GB free) and asks you to confirm.
The stored runs used a keyless internal build of the same release.
