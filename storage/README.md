# Storage benchmarks

How many bytes four real datasets take once stored in Elasticsearch 9.5.5 (standard and logsdb), OpenSearch 3.9.0 (default settings) and Cartridge.

Each dataset directory has:
- a `run.sh` that downloads the public data and runs every step as a visible command
- a README with the stored results and fairness notes
- the loaders and mappings it uses

Shared helpers are in [`../lib`](../lib). Stored results and logs are in [`../results/storage`](../results/storage).

## Method
- All sizes are primary store bytes: one shard, no replica, after a force-merge to one segment.
- Hardware: one AWS r7i.4xlarge (16 vCPU, 128 GB), on demand, no other load.
- Exception: the Elasticsearch and Cartridge sizes for Thunderbird, CockroachDB and CloudTrail were measured on a c7i.4xlarge with 30 GB (see each README).

## Results
Sizes in decimal GB. The factor in brackets is how many times larger than Cartridge level 2 that cell is.

| Dataset | raw | Elasticsearch standard | Elasticsearch logsdb | OpenSearch default | Cartridge level 2 | Cartridge level 1 |
|---|---:|---:|---:|---:|---:|---:|
| [Thunderbird syslog](thunderbird/README.md) | 10.7 GB | 7.42 GB (10.6x) | 2.40 GB (3.4x) | 7.61 GB (10.9x) | 0.701 GB | 0.526 GB |
| [CockroachDB JSON logs](cockroachdb/README.md) | 10.5 GB | 9.68 GB (12.6x) | 1.51 GB (2.0x) | 3.75 GB (4.9x) | 0.767 GB | 0.557 GB |
| [CloudTrail (flaws.cloud)](cloudtrail/README.md) | 2.39 GB | 1.44 GB (3.2x) | 1.00 GB (2.2x) [^ct] | 1.48 GB (3.2x) | 0.456 GB | 0.389 GB |
| [Alibaba traces as OTel spans](traces/README.md) | 19.7 GB | 5.20 GB (3.3x) | 4.56 GB (2.9x) | 9.47 GB (6.0x) | 1.57 GB | 1.05 GB |

[^ct]: CloudTrail logsdb: 1.00 GB with the four `flattened` fields (every field searchable); 0.842 GB (1.8x) for the stock logs data stream, where 20.9% of events are partly unsearchable.

### Sources
In the order of the columns:

| Dataset | Elasticsearch and Cartridge | OpenSearch |
|---|---|---|
| Thunderbird | [thunderbird-es955-cartridge.md](../results/storage/thunderbird-es955-cartridge.md) | [opensearch log, flush rerun](../results/storage/opensearch-default-real-r7i-4xlarge-2026-10-26-flush-tbcr.log) |
| CockroachDB | [cockroachdb-es955-cartridge.md](../results/storage/cockroachdb-es955-cartridge.md) | [opensearch log, flush rerun](../results/storage/opensearch-default-real-r7i-4xlarge-2026-10-26-flush-tbcr.log) |
| CloudTrail | [cloudtrail-es955-cartridge.md](../results/storage/cloudtrail-es955-cartridge.md) | [opensearch log, flush rerun](../results/storage/opensearch-default-real-r7i-4xlarge-2026-10-26-flush.log) |
| Traces | [traces-es955-cartridge.md](../results/storage/traces-es955-cartridge.md) | [opensearch log, flush rerun](../results/storage/opensearch-default-real-r7i-4xlarge-2026-10-26-flush.log) |

## Reading the table
- **Elasticsearch standard** is `index.mode=standard`.
  - CloudTrail needs four fields mapped `flattened` to be searchable at all.
  - The default dynamic mapping hits the 1,000-field limit and rejects 79.1% of events.
- **Elasticsearch logsdb** (free licence) stores `_source` as is. A paid licence can synthesise it; that setup was not measured here.
- **CockroachDB mappings:** Elasticsearch standard used dynamic mapping; OpenSearch uses an explicit `@timestamp` mapping with the rest dynamic.
- **CockroachDB Cartridge** numbers are from the `--gron` press (it flattens the JSON itself).
  - An earlier pipe-fed run was 5.7% / 8% smaller because it reordered records; it is not used.
- **OpenSearch Thunderbird and CockroachDB:** an earlier refresh-only measurement was 7.39 GB (7,388,032,630 B) and 3.72 GB (3,722,426,390 B).
  - The flush and settle step made no material difference (+3.1% / +0.8%).

## Running
```
storage/<dataset>/run.sh          # thunderbird, cockroachdb, cloudtrail or traces
```
Needs:
- a Linux box with Docker (run through `sudo`), `curl`, `jq`, `python3`, `uv` (and `gron` for CloudTrail)
- 150 to 250 GB of free disk and several hours

Cartridge step:
- Installs the public CLI with `curl -sSf https://cartridge.app/install | sh` and runs `cartpress press`.
- A press uses your pressing credit (25 GB free) and asks you to confirm.
- The stored runs used the same release built without the licence check, so they drew no pressing credit.
- Download the public release at [cartridge.app](https://cartridge.app).
