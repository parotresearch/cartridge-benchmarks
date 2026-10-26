# Microservice traces as OpenTelemetry spans: stored size

## Data
The [Alibaba cluster-trace-microservices-v2022](https://github.com/alibaba/clusterdata) call-graph traces, chunks `CallGraph_0` to `CallGraph_3`
(public, anonymous download from `aliopentrace.oss-cn-beijing.aliyuncs.com`; terms are in the Alibaba repository, not verified here). `alibaba_callgraph_to_otel.py` converts each CSV row to one OpenTelemetry span
in the layout Elasticsearch's stock `traces-otel@template` maps. Every output field is a copy or a pure function of one source column; spans with no recorded response time carry no duration.
Result: **19,744,374,361 bytes, 51,982,824 spans** (SHA-256 of the converted file is checked in `run.sh`).
The data is a flat table of hashed IDs (trace, service, instance, interface) plus a duration: no free text and no rich attributes.

## What `run.sh` does
| step | what it measures |
|---|---|
| 1 | Downloads the four chunks (SHA-256 checked), converts them in parallel, concatenates in chunk order, checks the SHA-256, bytes and span count of the result |
| 2 | **Elasticsearch 9.5.5 standard**: the stock `traces-otel@template` copied verbatim with only `index.mode=standard`, on a fresh node. Loader `load_es.py` (official Python client): 5,000-span batches, 8 workers. Refresh, count check, force-merge to 1 segment, primary store bytes |
| 3 | **Elasticsearch 9.5.5 logsdb**: the stock OTel trace stream (`traces-otel@template`, which is logsdb mode in 9.5.5; checked), fresh node, same loader and measurement |
| 4 | **OpenSearch 3.9.0, default settings**: `opensearch-mapping.json` (explicit and strict: `@timestamp` date, IDs and name `keyword`, `duration` long, attribute objects `flat_object`), 5,000-span batches, 8 workers. Force-merge to 1 segment, refresh, flush, settle, primary store bytes |
| 5 | **Cartridge**: `cartpress press spans.ndjson --gron -o traces-L2.cart -y`, and the same with `--level 1` |
| 6 | Prints a table of the sizes |

Containers are set up as in the [Thunderbird README](../thunderbird/README.md#what-runsh-does). Each Elasticsearch pass starts from an empty data directory.

## Stored result
Measured once on 2026-10-26 on one AWS r7i.4xlarge (16 vCPU, 128 GB), on demand, gp3 400 GB, nothing else running.

| system | stored bytes | x of raw | source |
|---|---:|---:|---|
| raw | 19,744,374,361 | 1.000 | |
| Elasticsearch 9.5.5 standard (stock OTel template, `index.mode: standard`) | 5,200,242,650 | 0.263 | [traces-es955-cartridge.md](../../results/storage/traces-es955-cartridge.md) |
| Elasticsearch 9.5.5 stock OTel trace stream (logsdb) | 4,560,877,302 | 0.231 | same file |
| OpenSearch 3.9.0 default, `flat_object` attributes | 9,471,101,499 | 0.480 | [opensearch log, flush rerun](../../results/storage/opensearch-default-real-r7i-4xlarge-2026-10-26-flush.log) (`RESULT forcemerge dataset=traces`) |
| Cartridge level 2 | 1,568,758,212 | 0.079 | [traces-es955-cartridge.md](../../results/storage/traces-es955-cartridge.md) |
| Cartridge level 1 | 1,048,451,721 | 0.053 | same file |

## Fairness notes
- **This is the dataset where the gap is smallest.** Short hashed IDs compress well in Elasticsearch doc values too; Cartridge level 2 is 2.9x smaller than the Elasticsearch logsdb index and 3.3x smaller than standard.
- **Elasticsearch loads faster here:** 509 to 590 s of load plus merge, against a 611 s press.
- **A plain `traces-<name>-default` stream is rejected.** Without the stock OTel template, all 52 million spans were rejected for their nested attribute keys, so the stock template is required.
- **OpenSearch has no OTel template.** Dynamic mapping would reject the dotted keys, so it uses an explicit mapping, which is why its size is not directly a "default Elasticsearch-style" comparison.
- **OpenSearch measurement.** A first pass reported 18,609,233,123 bytes before the flush-and-settle step existed (consistent with old files still awaiting deletion); the rerun that flushes and waits for the size to settle gave 9,471,101,499. `run.sh` performs that flush and settle wait.
- Pre-merge, Elasticsearch standard was 7.90 GB and logsdb 5.62 GB.
- Cartridge check: trace `T_21882887847` (line 1,000,001) has 3 spans in the NDJSON; both Cartridge levels and both Elasticsearch passes count 3.

## Notes
- **Cartridge.** The stored runs used cartpress 0.17.1 as a keyless internal build of the same release. A press with the public `cartpress` uses your pressing credit (25 GB free) and asks you to confirm. Each press asks you to confirm. Install: `curl -sSf https://cartridge.app/install | sh`.
