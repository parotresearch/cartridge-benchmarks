# Thunderbird syslog: stored size

## Data
The first 10 GiB of `Thunderbird.log` from the [Loghub](https://zenodo.org/records/8196385) collection (Zenodo record 8196385, licence CC-BY 4.0): supercomputer syslog,
one line per event, `- <epoch> <date> <host> <message>`. The cut is made at a line boundary: **10,737,418,238 bytes, 69,612,888 lines**.
12 lines hold invalid UTF-8. The Elasticsearch and OpenSearch loaders decode with replacement characters; Cartridge is pressed from a copy cleaned the same way (`clean_utf8.py`, 10,737,418,350 bytes).

## What `run.sh` does
| step | what it measures |
|---|---|
| 1 | Downloads the archive (SHA-256 checked), cuts the 10 GiB, checks bytes and line count against the stored run |
| 2 | **Elasticsearch 9.5.5 standard**: index `tb-standard`, `index.mode=standard`, 1 shard, 0 replicas, refresh off, `@timestamp` date + `message` text. Loader `bulk_load.py`: 20,000-line batches, 8 workers. Refresh, force-merge to 1 segment, primary store bytes |
| 3 | **Elasticsearch 9.5.5 logsdb**: the stock `logs-thunderbird-default` data stream (`index.mode=logsdb`, checked), 0 replicas, refresh off. Same loader and measurement |
| 4 | **OpenSearch 3.9.0, default settings**: `opensearch-mapping.json` (`@timestamp` date, `message` text), same batch and workers (`lib/load_os.py`), force-merge to 1 segment, refresh, flush, wait for the store size to settle, primary store bytes |
| 5 | **Cartridge**: `cartpress press tb10g.clean.log -o tb-L2.cart` (level 2, the default) and the same with `--level 1`; the file size is the result |
| 6 | Prints a table of the five sizes |

Elasticsearch runs in Docker `docker.elastic.co/elasticsearch/elasticsearch:9.5.5`: one node, security off, basic licence, 24 GB container (heap auto-sized), no telemetry.
OpenSearch runs in `opensearchproject/opensearch:3.9.0`: 24 GB container, 12 GB heap (set explicitly to match the heap Elasticsearch picks itself), security plugin off.

## Stored result
| system | stored bytes | x of raw | source |
|---|---:|---:|---|
| raw | 10,737,418,238 | 1.000 | |
| Elasticsearch 9.5.5 standard | 7,419,489,100 | 0.691 | [thunderbird-es955-cartridge.md](../../results/storage/thunderbird-es955-cartridge.md) |
| Elasticsearch 9.5.5 logsdb | 2,400,695,754 | 0.224 | same file |
| OpenSearch 3.9.0 default | 7,614,836,272 | 0.709 | [opensearch log, flush rerun](../../results/storage/opensearch-default-real-r7i-4xlarge-2026-10-26-flush-tbcr.log) (`RESULT forcemerge dataset=thunderbird`) |
| Cartridge level 2 | 701,303,359 | 0.065 | [thunderbird-es955-cartridge.md](../../results/storage/thunderbird-es955-cartridge.md) |
| Cartridge level 1 | 525,666,845 | 0.049 | same file |

Level 1 came out smaller than level 2 on this data; reported as measured.

## Notes
- **Hardware.** The OpenSearch number came from an AWS r7i.4xlarge (16 vCPU, 128 GB) on demand with no other load. The Elasticsearch and Cartridge numbers were measured on a c7i.4xlarge (16 vCPU, 30 GB); presses ran on a second box of that type. Stored size does not depend on the box.
- **Elasticsearch measurement.** Primary store after `_refresh` and `_forcemerge?max_num_segments=1`. No flush or settle wait was run for the Elasticsearch numbers; the OpenSearch step adds both.
- **OpenSearch measurement.** Force-merge, refresh, flush, then wait for the size to settle. An earlier refresh-only measurement was 7,388,032,630 B; the flush made no material difference (+3.1%).
- **Cartridge.** The stored runs used the same release built without the licence check, so they drew no pressing credit. A press with the public `cartpress` uses your pressing credit (25 GB free) and asks you to confirm. Install: `curl -sSf https://cartridge.app/install | sh`.
- **Not part of this repo's claim.** The original report also holds query latencies; those are in the speed benchmarks, not here.
