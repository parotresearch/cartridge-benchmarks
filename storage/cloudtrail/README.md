# CloudTrail audit logs (flaws.cloud): stored size

## Data
The public CloudTrail logs of the [flaws.cloud](https://flaws.cloud) training site, as published at `https://summitroute.com/downloads/flaws_cloudtrail_logs.tar`
(251,688,960 bytes; 20 files `flaws_cloudtrail*.json.gz`, 251,670,186 bytes of gzip, each `{"Records":[...]}`). One event per line after `jq -c '.Records[]'`:
**2,389,223,172 bytes, 1,939,207 events**, 1,181 distinct leaf paths. Licence: none stated on the download page (not verified further).

## What `run.sh` does
| step | what it measures |
|---|---|
| 1 | Downloads the tar (SHA-256 checked), unpacks the 20 files, writes one event per line, checks bytes and event count |
| 2 | **Elasticsearch 9.5.5 standard (index B)**: `requestParameters`, `responseElements`, `additionalEventData`, `serviceEventDetails` mapped `flattened`, everything else dynamic, 1 shard, 0 replicas. Loader `es_load.py` (kind `B`): 2,000-event batches; rejected events are counted, never retried. Force-merge to 1 segment, refresh, primary store bytes |
| 3 | **Elasticsearch 9.5.5 logsdb (index C)**: B plus `index.mode=logsdb`, with `eventTime` copied to `@timestamp` (logsdb requires it). Same measurement |
| 3b | **Elasticsearch 9.5.5 stock logs data stream (index D)**: `logs-cloudtrail-default`, no custom mapping or settings, `eventTime` copied to `@timestamp`. `es_load_datastream.py` loads, merges, and reports the settings, ignored fields and size |
| 4 | **OpenSearch 3.9.0, default settings**: `opensearch-mapping.json` (the same four fields as `flat_object`, the rest dynamic), 2,000-event batches, 1 worker, rejections counted. Force-merge to 1 segment, refresh, flush, settle, primary store bytes |
| 5 | **Cartridge**: flatten each event with `gron --stream` into one paragraph per event (4,094,934,200 bytes, 77,848,150 lines), then `cartpress press events.gron.txt --text-segment paragraph -o ct-L2.cart -y`, and the same with `--level 1` |
| 6 | Prints a table of the sizes |

Elasticsearch for this dataset ran with host networking, an 8 GB heap, the GeoIP downloader and disk watermark checks off (`es_up_8g_heap` in `lib/es.sh`); OpenSearch is set up as in the [Thunderbird README](../thunderbird/README.md#what-runsh-does).
An index A (default dynamic mapping) was also measured in the original run: 188,125,211 bytes, but 1,533,936 of 1,939,207 events (79.1%) were rejected by the 1,000-field limit. It is not in `run.sh` because it is not a usable setup; it is listed in the results file.

## Stored result
| system | stored bytes | x of raw | source |
|---|---:|---:|---|
| raw | 2,389,223,172 | 1.000 | |
| Elasticsearch 9.5.5 standard, 4 `flattened` fields (B) | 1,438,882,886 | 0.602 | [cloudtrail-es955-cartridge.md](../../results/storage/cloudtrail-es955-cartridge.md) |
| Elasticsearch 9.5.5 logsdb, same mapping (C) | 996,991,992 | 0.417 | same file |
| Elasticsearch 9.5.5 stock logs data stream (D) | 841,790,533 | 0.352 | same file |
| OpenSearch 3.9.0 default, `flat_object` fields | 1,476,093,976 | 0.618 | [opensearch log, flush rerun](../../results/storage/opensearch-default-real-r7i-4xlarge-2026-10-26-flush.log) (`RESULT forcemerge dataset=cloudtrail`) |
| Cartridge level 2 | 456,060,724 | 0.191 | [cloudtrail-es955-cartridge.md](../../results/storage/cloudtrail-es955-cartridge.md) |
| Cartridge level 1 | 389,109,483 | 0.163 | same file |

## Fairness notes
- **The stock Elasticsearch setup loses data silently.** With no custom mapping (D), no event is rejected, but 405,111 documents (**20.9% of events**) carry at least one field that is kept in `_source` and not searchable, because the stock template caps a document at 1,000 fields and ignores the rest. `_count` also returns 1,937,986, 1,221 fewer than the 1,939,207 the bulk API acknowledged (cause not investigated). D is the smallest Elasticsearch index, and it indexes less than B and C. B and C are the setups where every field is searchable.
- **B rejects 887 events** (dynamic date detection maps `apiVersion` as a date from the first value seen, and `2016_11_25` fails to parse); C accepts them (logsdb sets `ignore_malformed`). OpenSearch (`flat_object` fields, the rest dynamic) also rejects 887 events on the `apiVersion` date parse (1,938,320 indexed); its size is for those documents.
- **Cartridge searches every byte of the flattened text**, so nothing is skipped; the Elasticsearch comparison is about size at the fields each setup actually indexes.
- The first OpenSearch pass for this dataset reported 2,555,585,148 bytes before the flush-and-settle step existed (consistent with old files still awaiting deletion); the flush-and-settle rerun (1,476,093,976) is the stored number, and is what `run.sh` does.

## Not recorded
- The version of `gron` used for the stored carts was not recorded; `run.sh` uses the distribution package (`apt install gron`).
- How the node for index D was started is not recorded separately; `run.sh` uses the same node as B and C.

## Notes
- **Hardware.** The OpenSearch number came from an AWS r7i.4xlarge (16 vCPU, 128 GB) on demand with no other load. The Elasticsearch and Cartridge numbers were measured on a c7i.4xlarge (16 vCPU, 30 GB). Stored size does not depend on the box.
- **Cartridge.** The stored runs used a keyless internal build of the same release. A press with the public `cartpress` uses your pressing credit (25 GB free) and asks you to confirm; `run.sh` asks once up front and passes `-y` to the presses. Install: `curl -sSf https://cartridge.app/install | sh`.
