# CockroachDB JSON logs: stored size

## Data
- Source: [CockroachDB JSON Logs](https://zenodo.org/records/10516387) (Zenodo record 10516387, licence CC-BY 4.0).
- Archive: `cockroachdb.tar.gz`, 555 MB (554,664,494 bytes), holds one file, `cockroach.node1.log`.
- Content: NDJSON, one CockroachDB v22.2.6 structured log document per line.
- Size: **10.5 GB (10,506,623,721 bytes), 16,520,377 lines**. All of it is used.
- Long lines: 10,241 lines are longer than 60 KB (the longest is 1.95 MB).

## What `run.sh` does
| step | what it measures |
|---|---|
| 1 | Downloads the archive (SHA-256 checked), unpacks it, checks bytes and line count against the stored run |
| 2 | **Elasticsearch 9.5.5 standard**: index `cr-standard`, `index.mode=standard`, 1 shard, 0 replicas, `@timestamp` mapped as `date` (`epoch_millis`), every other field dynamic (146 mapped fields in the stored run). Loader `load.py` puts `@timestamp` (from the line's own `timestamp`) in front of each document: 4,000-line batches, 4 threads. Refresh, force-merge to 1 segment, primary store bytes |
| 3 | **Elasticsearch 9.5.5 logsdb**: the stock `logs-cockroach-default` data stream (created by the first bulk request; `index.mode=logsdb`, checked; 152 mapped fields in the stored run). Same loader and measurement |
| 4 | **OpenSearch 3.9.0, default settings**: `opensearch-mapping.json` (explicit `@timestamp` date mapping, everything else dynamic), 4,000-line batches, 4 workers, force-merge to 1 segment, refresh, flush, settle, primary store bytes |
| 5 | **Cartridge**: `cartpress press cockroach.node1.log --gron -o cr-L2.cart`, and the same with `--level 1`; the file size is the result |
| 6 | Prints a table of the five sizes |

Elasticsearch and OpenSearch containers are set up exactly as in the [Thunderbird README](../thunderbird/README.md#what-runsh-does).

## Stored result
Sizes in decimal GB. "vs Cartridge" is the size relative to Cartridge level 2.

| system | stored | x of raw | vs Cartridge | source |
|---|---:|---:|---:|---|
| raw | 10.5 GB | 1.000 | | |
| Elasticsearch 9.5.5 standard | 9.68 GB | 0.922 | 12.6x | [cockroachdb-es955-cartridge.md](../../results/storage/cockroachdb-es955-cartridge.md) |
| Elasticsearch 9.5.5 logsdb | 1.51 GB | 0.143 | 2.0x | same file |
| OpenSearch 3.9.0 default | 3.75 GB | 0.357 | 4.9x | [opensearch log, flush rerun](../../results/storage/opensearch-default-real-r7i-4xlarge-2026-10-26-flush-tbcr.log) (`RESULT forcemerge dataset=cockroachdb`) |
| Cartridge level 2, `--gron` | 0.767 GB | 0.073 | 1.0x | the rerun section of [cockroachdb-es955-cartridge.md](../../results/storage/cockroachdb-es955-cartridge.md) |
| Cartridge level 1, `--gron` | 0.557 GB | 0.053 | 0.7x | same section |

## Fairness notes
- **Mappings differ between systems.**
  - Elasticsearch standard used dynamic mapping apart from `@timestamp`; OpenSearch uses an explicit `@timestamp` mapping and dynamic for the rest.
  - Both index the same documents (16,520,377 each, 0 rejections).
  - Standard-mode Elasticsearch is 9.68 GB while OpenSearch with a near-identical mapping is 3.75 GB; the difference is not diagnosed here.
- **Cartridge numbers are from the `--gron` press**, which flattens the JSON itself and reads the file in place and in order.
  - An earlier run fed Cartridge through a pipe from the external `gron` tool. It moved the 10,241 largest lines to the end and measured 0.725 GB (725,298,523 B, level 2) and 0.516 GB (515,851,031 B, level 1).
  - Reordering made it 5.7% / 8% smaller, so those are not used. Both are in the results file.
- **The Elasticsearch free licence stores `_source` as is** in logsdb mode; a paid licence can synthesise it. No paid configuration was measured here.

## Notes
- **Hardware.**
  - OpenSearch: AWS r7i.4xlarge (16 vCPU, 128 GB), on demand, no other load.
  - Elasticsearch and Cartridge: c7i.4xlarge (16 vCPU, 30 GB).
  - Stored size does not depend on the box.
- **Elasticsearch measurement.** Primary store after `_refresh` and `_forcemerge?max_num_segments=1`; no flush or settle wait.
- **OpenSearch measurement.** An earlier refresh-only measurement was 3.72 GB (3,722,426,390 B); the flush made no material difference (+0.8%).
- **Cartridge.**
  - The stored runs used the same release built without the licence check, so they drew no pressing credit.
  - A press with the public `cartpress` uses your pressing credit (25 GB free) and asks you to confirm.
  - Install: `curl -sSf https://cartridge.app/install | sh`.
