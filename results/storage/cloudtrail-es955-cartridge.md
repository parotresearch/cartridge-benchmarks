# CloudTrail (flaws.cloud): Elasticsearch 9.5.5 vs Cartridge

Storage and load-time sections of the original run report. The query tables of that report are not reproduced here.

Box: c7i.4xlarge, 16 vCPU, 30 GB. Data: 20 `flaws_cloudtrail*.json.gz` (251,670,186 B gz), each `{"Records":[...]}`.

## Sizes

| item | value |
|---|---|
| NDJSON (one event per line) | 2,389,223,172 B, 1,939,207 events |
| gron text (paragraph per event) | 4,094,934,200 B, 77,848,150 lines |
| **distinct leaf paths** (gron, array indices stripped) | **1,181** (634 under `requestParameters`) |
| Cartridge level 2 | 456,060,724 B (19.1% of NDJSON) press 83 s |
| Cartridge level 1 | 389,109,483 B (16.3% of NDJSON) press 84 s |
| Elasticsearch A, default dynamic mapping | 188,125,211 B, **405,271 of 1,939,207 indexed, 1,533,936 rejected (79.1%)** |
| Elasticsearch B, 4 fields `flattened` | 1,438,882,886 B, 1,938,320 indexed, 887 rejected |
| Elasticsearch C, B + `index.mode: logsdb` (eventTime copied to `@timestamp`) | 996,991,992 B, 1,939,207 indexed, 0 rejected |
| Elasticsearch D, stock data stream `logs-cloudtrail-default` (no custom mapping; eventTime copied to `@timestamp`) | 841,790,533 B, 1,939,207 acknowledged, 0 rejected, **but only 1,937,986 searchable** |

Elasticsearch store = primary store bytes after `_forcemerge?max_num_segments=1` + `_refresh`. Presses ran one after the other, nothing else running on the box (press times are single runs). Elasticsearch load times (A 77 s, B 102 s, C 143 s, D 149 s) are single runs with no other heavy process; load average not recorded for them.
Elasticsearch single node, 8 GB heap, security off, geoip downloader off, basic licence, 1 shard 0 replicas for A/B/C (D keeps the stock 1 replica).

## What happens in each Elasticsearch index
- **A**: 1,000-field limit. Top reject reason: `Limit of total fields [1000] has been exceeded while adding new fields [N]` (all five most common reasons are this error). Mapping stalls at 858 type entries; later events with new paths are rejected whole.
- **B**: flattened mapping avoids the limit. 887 events are still rejected for a different reason: dynamic date detection mapped `apiVersion` as `date` from the first value seen, then `2016_11_25` fails to parse.
- **C**: logsdb sets `ignore_malformed`, so those 887 are accepted (the bad value goes to `_ignored`). Smaller than B by 31%.
- **D (stock logs data stream)**: **no rejections, but fields are silently dropped from the index.** Effective settings: `index.mode=logsdb`, `total_fields.limit=1000`, `total_fields.ignore_dynamic_beyond_limit=true`, `ignore_malformed=true`. 405,111 docs (20.9%) carry at least one `_ignored` field, i.e. a value that is stored in `_source` but not searchable. Top ignored: `userIdentity.sessionContext.webIdFederationData` 297,921 docs, `additionalEventData.CipherSuite` 63,503, `…AuthenticationMethod` 62,456, `…SignatureVersion` 62,456, `requestParameters.host` 37,024, `additionalEventData.x-amz-id-2` 26,495, `responseElements.credentials.sessionToken` 22,834 (40 buckets in the load report). Mapped field count: 813 type entries. Every string is a `keyword` with `ignore_above` 1024 (no text field, so no analysed search). Also: `_count` returns 1,937,986, 1,221 fewer than the 1,939,207 the bulk API acknowledged; cause not investigated. Single-node cluster stays yellow (default 1 replica).
