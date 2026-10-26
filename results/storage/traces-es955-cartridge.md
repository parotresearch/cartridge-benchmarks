# Alibaba microservice traces: Cartridge vs Elasticsearch 9.5.5 (size and load time)

Measured once, 2026-10-26, one r7i.4xlarge (16 vCPU), gp3 400 GB, on demand. Cartridge: cartpress 0.17.1 (internal build without a licence key).

**Data:** Alibaba cluster-trace-microservices-v2022 CallGraph, chunks 0–3 (anonymous download, SHA-256 in `storage/traces/run.sh`), converted by
`storage/traces/alibaba_callgraph_to_otel.py` to OTel span NDJSON in the layout Elasticsearch's stock `traces-otel@template` maps:
19,744,374,361 B, 51,982,824 spans. Every field is a copy or pure function of one source column; rt=None spans carry no duration.
The data is a flat table of hashed IDs (trace, service, instance, interface) plus a duration: no free text, no rich attributes.

| System | Stored bytes | ÷ raw | Cartridge L2 smaller by | Load s | Merge s | Load + merge s | Peak RSS |
|---|---|---|---|---|---|---|---|
| Elasticsearch standard (stock OTel template, `index.mode: standard`) | 5,200,242,650 | 0.263 | 3.31× | 328.9 | 260.8 | 589.7 | JVM 19.0 GB (container cap 24 GiB) |
| Elasticsearch stock OTel trace stream (`traces-otel@template` → logsdb, free licence, stored `_source`) | 4,560,877,302 | 0.231 | 2.91× | 308.7 | 200.6 | 509.3 | JVM 18.6 GB |
| Cartridge gron L2 | 1,568,758,212 | 0.079 | — | press 610.9 | — | 610.9 | 16.4 GB |
| Cartridge gron L1 | 1,048,451,721 | 0.053 | 0.67× of L2 (Elasticsearch standard 4.96×, logsdb 4.35×) | press 613.0 | — | 613.0 | 17.1 GB |

Correctness check: trace `T_21882887847` (line 1,000,001) has 3 spans in the NDJSON; Cartridge L2/L1 (quoted and unquoted) and both Elasticsearch passes count 3.

## Readings
- Elasticsearch 9.5.5's stock OTel trace store is **logsdb**, so for OTel traces into Elasticsearch 9.x the default comparator is logsdb.
- The multiple is the smallest of any dataset: short hashed IDs compress well in Elasticsearch doc values too. Cartridge is 2.9–5.0× smaller.
- **Elasticsearch loads faster here** (509–590 s load+merge vs 611 s press).
- A `traces-<name>-default` stream (no template) rejected all 52M spans (nested OTel attribute keys); the stock OTel template is required.
- Pre-merge: Elasticsearch standard 7.90 GB, logsdb 5.62 GB.
