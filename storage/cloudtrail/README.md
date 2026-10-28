# CloudTrail audit logs (flaws.cloud): stored size

## Data
- Source: the public CloudTrail logs of the [flaws.cloud](https://flaws.cloud) training site, published at `https://summitroute.com/downloads/flaws_cloudtrail_logs.tar`.
- Download: 252 MB (251,688,960 bytes); 20 files `flaws_cloudtrail*.json.gz`, 252 MB (251,670,186 bytes) of gzip, each `{"Records":[...]}`.
- Prepared with `jq -c '.Records[]'`, one event per line: **2.39 GB (2,389,223,172 bytes), 1,939,207 events**, 1,181 distinct leaf paths.
- Licence: none stated on the download page (not verified further).

## What `run.sh` does
| step | what it measures |
|---|---|
| 1 | Downloads the tar (SHA-256 checked), unpacks the 20 files, writes one event per line, checks bytes and event count |
| 2 | **Elasticsearch 9.5.5 standard (index B)**: `requestParameters`, `responseElements`, `additionalEventData`, `serviceEventDetails` mapped `flattened`, everything else dynamic, 1 shard, 0 replicas. Loader `es_load.py` (kind `B`): 2,000-event batches; rejected events are counted, never retried. Force-merge to 1 segment, refresh, primary store bytes |
| 3 | **Elasticsearch 9.5.5 logsdb (index C)**: B plus `index.mode=logsdb`, with `eventTime` copied to `@timestamp` (logsdb requires it). Same measurement |
| 3b | **Elasticsearch 9.5.5 stock logs data stream (index D)**: `logs-cloudtrail-default`, no custom mapping or settings, `eventTime` copied to `@timestamp`. `es_load_datastream.py` loads, merges, and reports the settings, ignored fields and size |
| 4 | **OpenSearch 3.9.0, default settings**: `opensearch-mapping.json` (the same four fields as `flat_object`, the rest dynamic), 2,000-event batches, 1 worker, rejections counted. Force-merge to 1 segment, refresh, flush, settle, primary store bytes |
| 5 | **Cartridge**: flatten each event with `gron --stream` into one paragraph per event (4.09 GB, 4,094,934,200 bytes, 77,848,150 lines), then `cartpress press events.gron.txt --text-segment paragraph -o ct-L2.cart`, and the same with `--level 1` |
| 6 | Prints a table of the sizes |

Setup notes:
- Elasticsearch for this dataset ran with host networking, an 8 GB heap, the GeoIP downloader and disk watermark checks off (`es_up_8g_heap` in `lib/es.sh`).
- OpenSearch is set up as in the [Thunderbird README](../thunderbird/README.md#what-runsh-does).
- An index A (default dynamic mapping) was also measured in the original run: 0.188 GB (188,125,211 bytes), but 1,533,936 of 1,939,207 events (79.1%) were rejected by the 1,000-field limit.
  - It is not in `run.sh` because it is not a usable setup; it is listed in the results file.

## Stored result
Sizes in decimal GB. "vs Cartridge" is the size relative to Cartridge level 2.

| system | stored | x of raw | vs Cartridge | source |
|---|---:|---:|---:|---|
| raw | 2.39 GB | 1.000 | | |
| Elasticsearch 9.5.5 standard, 4 `flattened` fields (B) | 1.44 GB | 0.602 | 3.2x | [cloudtrail-es955-cartridge.md](../../results/storage/cloudtrail-es955-cartridge.md) |
| Elasticsearch 9.5.5 logsdb, same mapping (C) | 1.00 GB | 0.417 | 2.2x | same file |
| Elasticsearch 9.5.5 stock logs data stream (D) | 0.842 GB | 0.352 | 1.8x | same file |
| OpenSearch 3.9.0 default, `flat_object` fields | 1.48 GB | 0.618 | 3.2x | [opensearch log, flush rerun](../../results/storage/opensearch-default-real-r7i-4xlarge-2026-10-26-flush.log) (`RESULT forcemerge dataset=cloudtrail`) |
| Cartridge level 2 | 0.456 GB | 0.191 | 1.0x | [cloudtrail-es955-cartridge.md](../../results/storage/cloudtrail-es955-cartridge.md) |
| Cartridge level 1 | 0.389 GB | 0.163 | 0.9x | same file |

## Fairness notes
- **The stock Elasticsearch setup (D) loses data silently.**
  - No event is rejected, but 405,111 documents (**20.9% of events**) carry at least one field that is kept in `_source` and not searchable.
  - Cause: the stock template caps a document at 1,000 fields and ignores the rest.
  - `_count` returns 1,937,986, which is 1,221 fewer than the 1,939,207 the bulk API acknowledged (cause not investigated).
  - D is the smallest Elasticsearch index, and it indexes less than B and C. B and C are the setups where every field is searchable.
- **B rejects 887 events.**
  - Dynamic date detection maps `apiVersion` as a date from the first value seen, and `2016_11_25` fails to parse.
  - C accepts them (logsdb sets `ignore_malformed`).
  - OpenSearch (`flat_object` fields, the rest dynamic) also rejects 887 events on the `apiVersion` date parse (1,938,320 indexed); its size is for those documents.
- **Cartridge searches every byte of the flattened text**, so nothing is skipped; the Elasticsearch comparison is about size at the fields each setup actually indexes.
- **OpenSearch first pass:** 2.56 GB (2,555,585,148 bytes), before the flush-and-settle step existed (consistent with old files still awaiting deletion).
  - The flush-and-settle rerun (1.48 GB, 1,476,093,976 bytes) is the stored number, and is what `run.sh` does.

## Not recorded
- The version of `gron` used for the stored carts was not recorded; `run.sh` uses the distribution package (`apt install gron`).
- How the node for index D was started is not recorded separately; `run.sh` uses the same node as B and C.

## Notes
- **Hardware.**
  - OpenSearch: AWS r7i.4xlarge (16 vCPU, 128 GB), on demand, no other load.
  - Elasticsearch and Cartridge: c7i.4xlarge (16 vCPU, 30 GB).
  - Stored size does not depend on the box.
- **Cartridge.**
  - The stored runs used the same release built without the licence check, so they drew no pressing credit.
  - A press with the public `cartpress` uses your pressing credit (25 GB free) and asks you to confirm.
  - Install: `curl -sSf https://cartridge.app/install | sh`.
