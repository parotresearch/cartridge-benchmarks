# CockroachDB JSON logs (Zenodo 10516387): Elasticsearch 9.5.5 vs Cartridge

Storage and load-time sections of the original run reports (two reports: a first run that fed Cartridge through a `gron` pipe, then a rerun with
`cartpress press --gron`). The query-latency tables are not reproduced here.

Box: c7i.4xlarge (16 vCPU, 30 GB), one box, Elasticsearch and Cartridge never running together.
Data: `cockroachdb.tar.gz` (554,664,494 B) holds ONE file, `cockroach.node1.log`: NDJSON (one JSON document per line, CockroachDB v22.2.6 structured logs),
**10,506,623,721 B, 16,520,377 lines/docs**, all of it used. 10,241 lines are over 60 KB (max 1.95 MB).

## Sizes, first run (Cartridge fed through a `gron` pipe)
| | bytes | x of raw | vs raw |
|---|---:|---:|---:|
| raw NDJSON | 10,506,623,721 | 1.000 | 1× |
| Elasticsearch logsdb (`logs-cockroach-default`, 152 mapped fields, stored `_source`) | 1,506,138,614 | 0.143 | 7.0× smaller |
| Elasticsearch standard (`cr-standard`, 146 mapped fields) | 9,682,259,352 | 0.922 | 1.1× smaller |
| Cartridge level 2 (default), `gron` pipe | 725,298,523 | 0.069 | 14.5× smaller |
| Cartridge level 1, `gron` pipe | 515,851,031 | 0.049 | 20.4× smaller |

Elasticsearch bytes = primary store, after `_refresh` + `_forcemerge?max_num_segments=1`; docs count = 16,520,377 in both = lines, 0 bulk rejections, 0 `@timestamp` parse failures, no mapping-limit trouble.
`logs-cockroach-default` verified `index.mode=logsdb` (sort `host.name`, `@timestamp`); the free (basic) licence stores `_source` rather than synthesising it.

## Load / press times, first run
| step | wall |
|---|---:|
| Elasticsearch logsdb: bulk load (4 threads, 4000 docs/bulk, 24 GB container) / + refresh + merge | 162.5 s / 320.2 s |
| Elasticsearch standard: bulk load / + refresh + merge | 173.8 s / 474.4 s |
| gron stage (12,821,325,855 B of text; see deviation) | 736.6 s |
| cartpress level 2 (default), peak RSS 9.1 GB | 230.1 s |
| cartpress level 1, peak RSS 8.5 GB | 231.3 s |

**Deviation:** `gron --stream` aborts on this file (`bufio.Scanner: token too long`). The 16,510,136 lines under 60 KB went through `gron --stream` exactly as specified; the 10,241 larger lines went through plain `gron`, one document at a time, same output shape. Document order differs from the file (big ones last); counts are unaffected.
Level 1 is smaller than level 2 here, and presses in the same time.

## Rerun with native `cartpress press --gron` (no pipe, no split)

One run per level on a fresh c7i.4xlarge, nothing else running (load before level 1 = 17.2, the decaying level 2 press).
Input: the same 10,506,623,721 B NDJSON, 16,520,377 lines, 10,240 lines over 64 KiB (the pipe run split at 60,000 B and found 10,241). The native press read every line in place; no error, no split.

| | gron pipe (first run) | native `--gron` |
|---|---:|---:|
| level 2 cart | 725,298,523 (0.069 of raw) | **766,850,694 (0.073)**, +5.7% |
| level 1 cart | 515,851,031 (0.049) | **557,402,533 (0.053)**, +8% |
| level 2 time | 737 s gron + ~230 s press = ~967 s | **263.6 s** (3.7x faster; Elasticsearch logsdb 162 s load, 320 s with merge) |
| level 1 time | 737 s gron + ~231 s press | 261.5 s |

The pipe run reordered records: it converted the 16,510,136 small lines first and **appended the 10,241 big lines (60 KB-1.9 MB) at the end**, grouping similar huge records together, which compresses better. The native press keeps the file's original order.
**The native carts are the honest numbers**; the first-run cart sizes were 5.7% (level 2) / 8% (level 1) optimistic. Against Elasticsearch logsdb (1,506,138,614 B): level 2 1.96x smaller (was 2.08x), level 1 2.70x (was 2.92x).
`storage/cockroachdb/run.sh` uses the native press, so its Cartridge numbers are the rerun's.
