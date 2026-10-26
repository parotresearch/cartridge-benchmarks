# Thunderbird (Loghub), first 10 GiB: Elasticsearch 9.5.5 vs Cartridge

Storage and load-time sections of the original run report. The query-latency tables of that report are not reproduced here.

Data: first 10 GiB of `Thunderbird.log` cut at a line boundary = **10,737,418,238 B, 69,612,888 lines** (avg 154 B/line; supercomputer syslog,
`- <epoch> <date> <host> <syslog line>`). 12 lines (1,084 raw bytes) hold invalid UTF-8; both engines saw U+FFFD for them
(the Elasticsearch loader decodes with `errors="replace"`; Cartridge was pressed from a copy cleaned the same way, 10,737,418,350 B). Lines with no parseable epoch: **0**.

Boxes: Elasticsearch load on a c7i.4xlarge (16 vCPU, 30 GB, Ubuntu 24.04). Presses ran on a second box of the same type.
Elasticsearch: Docker image `elasticsearch:9.5.5`, single node, security off, no telemetry, basic licence (no trial started).
Load shape: 24 GB container (auto heap), uncapped CPU, 8 bulk workers, refresh off.

## Sizes
| | bytes | x of raw |
|---|---:|---:|
| raw (10 GiB cut) | 10,737,418,238 | 1.00 |
| Elasticsearch `logs-thunderbird-default` (data stream, **index.mode=logsdb**, verified in `_settings`) | 2,400,695,754 | 0.224 (4.5× smaller) |
| Elasticsearch `tb-standard` (mode standard, message text, @timestamp date) | 7,419,489,100 | 0.691 (1.4× smaller) |
| Cartridge level 2 (default) | 701,303,359 | 0.065 (15.3× smaller) |
| Cartridge level 1 (`--level 1`) | 525,666,845 | 0.049 (20.4× smaller) |

Elasticsearch = primary store after `_refresh` + `_forcemerge?max_num_segments=1`, 1 shard, 0 replicas; docs = 69,612,888 in both (equal to the line count).
Cartridge was pressed as plain text. **Level 1 came out smaller than level 2** here; reported as measured.

## Load / press times
| | wall |
|---|---:|
| Elasticsearch logsdb bulk load | 258 s (+116 s refresh/forcemerge) |
| Elasticsearch standard bulk load | 235 s (+349 s refresh/forcemerge) |
| Cartridge press level 2 | 238.7 s (load average 1.1 before; box quiet) |
| Cartridge press level 1 | 233.9 s (load average was still 21.7 at start, decaying from the level 2 press, not a third party) |
