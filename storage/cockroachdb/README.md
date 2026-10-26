# CockroachDB JSON logs: stored size

## Data
[CockroachDB JSON Logs](https://zenodo.org/records/10516387) (Zenodo record 10516387, licence CC-BY 4.0). `cockroachdb.tar.gz` (554,664,494 bytes) holds one file, `cockroach.node1.log`:
NDJSON, one CockroachDB v22.2.6 structured log document per line, **10,506,623,721 bytes, 16,520,377 lines**. All of it is used. 10,241 lines are longer than 60 KB (the longest is 1.95 MB).

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
| system | stored bytes | x of raw | source |
|---|---:|---:|---|
| raw | 10,506,623,721 | 1.000 | |
| Elasticsearch 9.5.5 standard | 9,682,259,352 | 0.922 | [cockroachdb-es955-cartridge.md](../../results/storage/cockroachdb-es955-cartridge.md) |
| Elasticsearch 9.5.5 logsdb | 1,506,138,614 | 0.143 | same file |
| OpenSearch 3.9.0 default | 3,722,426,390 | 0.354 | [opensearch log, second pass](../../results/storage/opensearch-default-real-r7i-4xlarge-2026-10-26.log) (`RESULT forcemerge dataset=cockroachdb`) |
| Cartridge level 2, `--gron` | 766,850,694 | 0.073 | same cockroachdb file, "Rerun with native `cartpress press --gron`" |
| Cartridge level 1, `--gron` | 557,402,533 | 0.053 | same section |

## Fairness notes
- **Mappings differ between systems.** Elasticsearch standard used dynamic mapping apart from `@timestamp`; OpenSearch uses an explicit `@timestamp` mapping and dynamic for the rest. Both index the same documents (16,520,377 each, 0 rejections). The standard-mode Elasticsearch index is 9.68 GB while OpenSearch with a near-identical mapping is 3.72 GB; the difference is not diagnosed here.
- **Cartridge numbers are from the native `--gron` press**, which reads the file in place and in order. An earlier run fed Cartridge through a `gron` pipe that moved the 10,241 largest lines to the end and measured 725,298,523 (level 2) and 515,851,031 (level 1) bytes; reordering made it 5.7% / 8% smaller, so those are not used. Both are in the results file.
- **The Elasticsearch free licence stores `_source` as is** in logsdb mode; a paid licence can synthesise it. No paid configuration was measured here.

## Notes
- **Hardware.** The OpenSearch number came from an AWS r7i.4xlarge (16 vCPU, 128 GB) on demand with no other load. The Elasticsearch and Cartridge numbers were measured on a c7i.4xlarge (16 vCPU, 30 GB). Stored size does not depend on the box.
- **Elasticsearch measurement.** Primary store after `_refresh` and `_forcemerge?max_num_segments=1`; no flush or settle wait. The stored OpenSearch number came from an earlier version of the OpenSearch script without the flush and settle; a rerun of `run.sh` may report a slightly lower number. Not re-measured.
- **Cartridge.** The stored runs used a keyless internal build of the same release. A press with the public `cartpress` uses your pressing credit (25 GB free) and asks you to confirm. Install: `curl -sSf https://cartridge.app/install | sh`.
