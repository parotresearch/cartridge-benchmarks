# http_logs: stored size and search speed

The 1998 World Cup web logs (the `http_logs` dataset of the Rally benchmark suite): 247,249,096 log lines, 23.5 GB
of raw text (23,475,280,341 bytes).

This directory reproduces two sets of claims:

- how much space each system needs;
- how fast 39 investigation searches run on three storage tiers.

Everything that produced a number is a script here. The logs they produced are in
[`../../results/speed/http_logs`](../../results/speed/http_logs); the tables below name each one.

## Claims and where they come from

| Claim | Cartridge | Elasticsearch |
|---|---|---|
| Hot: 39 searches, local disk | 11.0 s, 39 of 39 exact | 11.5 s, 34 of 39 exact |
| Warm: first answer | 9–10 s | 30–71 s |
| Warm: all 39 once local | 9.9 s | 9.6 s |
| Cold: the 35 searches both answer | 63 s† | 290 s |

† A fix for Cartridge's cold-from-S3 time is in progress, so the 63 s will change.

Result files, all under `speed/`:

| Claim | Cartridge log | Elasticsearch log |
|---|---|---|
| Hot | `hot-cart-field-index.log` | `hot-es.log` |
| Warm: first answer | `warm-cart-field-index.log` | `warm-es-fullcopy.log` (30–47 s), `warm-es-restore.log` (64–71 s) |
| Warm: all 39 once local | `warm-cart-field-index.log` | `warm-es-restore.log` |
| Cold | `cold-cart.log` | `cold-es-frozen.log` |

`uv run ../lib/summarize.py ../../results/speed/http_logs/speed` re-derives every number in the claims table from the
stored logs (it only reads them).

Stored size of the 247,249,096 lines (raw text is 23.5 GB; "vs Cartridge" is relative to the 2.98 GB total):

| System and setting | Size | vs Cartridge |
|---|---:|---:|
| Elasticsearch 9.5.4, standard, merged to one segment per shard | 22.5 GB | 7.6× |
| Elasticsearch 9.5.4, standard, restored from the speed-run snapshot (hot restore; cost-model default) | 18.7 GB | 6.3× |
| OpenSearch 3.9.0, default settings | 19.5 GB | 6.5× |
| Elasticsearch 9.5.4 logsdb, free licence | 10.6 GB | 3.5× |
| Elasticsearch 9.5.4 logsdb, Enterprise licence (synthetic source) | 6.49 GB | 2.2× |
| Cartridge, default flags (cart) | 2.12 GB | 0.71× |
| Cartridge field index (extra file, used by the faster rows above) | 0.860 GB | 0.29× |
| **Cartridge total, cart + field index** | **2.98 GB** | **1.0× (0.127× of raw)** |

Result files, all under `size/`:

| Row | File |
|---|---|
| Elasticsearch standard, merged | `es-standard-and-press-r7i-4xlarge-2026-10-21.log` |
| Elasticsearch standard, hot restore | `es-hot-restore-c7i-4xlarge-2026-10-07.log` |
| OpenSearch default | `opensearch-3.9.0-default-r7i-4xlarge-2026-10-25.log` |
| Elasticsearch logsdb (free and Enterprise) | `es-logsdb-r7i-4xlarge-2026-10-25.log` |
| Cartridge cart, field index, total | `../verify/httplogs-verify-r7i-4xlarge-2026-10-26.log` |

Exact byte counts are in those logs.

About the Cartridge size:

- The published size is the total, including the field index.
- It comes from the verification run of 2026-10-26 (`../../../results/speed/http_logs/verify/`).
- In that run the default-flag press took 564 s and the field index build 191 s.
- All 48 search runs matched the answers computed from the raw text (see below).
- It supersedes the earlier stored sizes: 3.24 GB for the cart (3,237,744,683 bytes) and 0.860 GB for the field index (859,679,538 bytes); `size/cartpress-…` and `size/field-index-build-…`.

## What to run

```sh
export BUCKET=<your-s3-bucket>           # snapshots and the cart live here; you need read and write on it
./00-data.sh                             # download the 7 weekly files, check sizes, line count and three oracle counts
./10-size.sh [es|logsdb|opensearch|cartridge|all]
./20-speed.sh setup                      # load Elasticsearch, snapshot it, press Cartridge, upload both
./20-speed.sh all                        # or one arm: hot-es hot-cart warm-es-restore warm-es-fullcopy warm-cart cold-es cold-cart
```

**Machine**

- AWS in one region, Ubuntu with Docker, `uv`, `jq`, `lbzip2`, the AWS CLI v2.
- An instance role with access to `$BUCKET`. Elasticsearch reaches S3 through the instance metadata service; set the metadata hop limit to 2 so containers can.
- Speed runs: c7i.4xlarge (16 vCPU, 32 GiB, gp3 volume at 16,000 IOPS and 1,000 MB/s).
- Loading and pressing: r7i.4xlarge.

**Cartridge**

- Install: `curl -sSf https://cartridge.app/install | sh` (installs `cartridge` and `cartpress`).
- **Pressing uses your account's pressing credit and asks you to confirm.**
- Our runs used the same release built without the licence check, so they drew no pressing credit.
- Download the public release at [cartridge.app](https://cartridge.app).

**Not for a laptop.** The scripts start Docker containers, move about 100 GB and take hours.

## The scripts

| File | What it does |
|---|---|
| `00-data.sh` | Downloads the dataset, unpacks the raw log line of each record, verifies byte counts, line count and the 403/404/500 oracle counts (224 / 1,224,876 / 6,134). Prints the SHA-256 of every download. |
| `10-size.sh` | The size passes: Elasticsearch standard, logsdb (free and Enterprise), OpenSearch default, Cartridge press and field index. Each prints `RESULT ... bytes` lines. |
| `20-speed.sh` | The tier arms. The commands that matter (caps, cache drops, what is timed from when) are in this file; boilerplate is in `../lib`. |
| `searches.json` | The 39 searches, 8 chains. Each carries the Elasticsearch query body and the Cartridge command side by side, the expected answer, and the kind of answer. |
| `reference/` | The full match set of each of the 8 `lines` searches (gzipped), used to check returned lines. |
| `rally-track/`, `es-index-template.json` | The Rally track and index template used to load Elasticsearch. |
| `reference.py` | Computes the expected answer of every search from the raw text (see below). |
| `verify_cart.py` | Runs the 39 searches once on a local cart and compares each answer with `reference-answers.json`. |
| `../lib/run_searches.py` | Runs one chain, times each search, reduces each answer to a canonical text and judges it. |
| `../lib/summarize.py` | Reads the stored logs and prints the claims table. |

## The tiers in plain words

**Hot.** Data on local disk, server running, file cache dropped before each chain.

- Elasticsearch: indices restored from a snapshot to local disk, no replicas.
- Cartridge: the cart (and its field index) is copied from S3 to local disk once.

**Warm.** Data in S3, fresh server. The clock starts when the server is up and holds nothing.

- Elasticsearch, restore: restore the snapshot to local disk; searches begin when it finishes (first answer 64–71 s).
- Elasticsearch, full copy: a fully mounted searchable snapshot answers while it is copied (first answer 30–47 s).
- The claim's 30–71 s spans both. After the copy finishes the script checks that the bytes on disk and the index store size both cover the snapshot's size.
- Cartridge: copy the cart and field index from S3 to local disk, then search. The first answer includes the copy.
- "All 39 once local" is the sum of the 39 search times when the data is local.

**Cold.** Data stays in S3; every search reads what it needs from there.

- Elasticsearch: searchable snapshots in the frozen tier, with a cache one twentieth the size of the data.
- Cartridge: the server opens `s3://` directly; the field index is never read from S3.

## How exactness was checked

Each search has an expected answer in `searches.json` (`want`). The runner reduces each system's output to one
canonical text per kind of answer and compares it:

- **count** – a single number.
- **lines** – any 100 matching lines (both systems stop at 100). Each returned line must be in the search's full
  match set (`reference/`), counting duplicates; the count must be exactly `min(100, total)`.
- **per-day / per-hour counts** – the non-empty buckets (UTC days; hours in local time, UTC-5).
- **top-N** – exactly N rows `key<TAB>count`, sorted by count descending then key ascending; the answer is the
  SHA-256 of that text. Cartridge's answer is refused if it is flagged approximate.

Both systems' canonical texts for every search that both answered are byte-identical (`out_sha` in the logs;
`summarize.py` reports any mismatch and finds none).

**Where the expected answers come from**

- `reference.py` reads the raw log text: one streaming pass, standard library only, no Cartridge or Elasticsearch involved.
- It computes each search's answer from the lines themselves, using the pattern, time window and grouping of the search's Cartridge command.
- It writes `reference-answers.json`: per search, the answer, the sha256 of the canonical text, and for `lines` searches the full match set.
- `verify_cart.py` runs the 39 searches on a local cart and compares each with that file.

**What "exact" means**

- "Exact" means "matched `reference.py`'s answer from the raw file", and only for searches that have a computed entry in `reference-answers.json` and a recorded `match`.
- A search that `reference.py` cannot compute without guessing is marked "not computable" with the reason, and is not claimed exact on this basis.

**Verification run of 2026-10-26** (`../../results/speed/http_logs/verify/`), on a fresh press with the default flags:

- `reference.py` took 4 min 16 s over the 23,475,280,341 raw bytes (247,249,096 lines).
- `verify_cart.py` ran the 39 searches as 48 runs (the nine searches that have a field-index form ran in both forms).
- Result: **48 matches, 0 mismatches**.
- This supersedes the earlier practice of taking the expected answers from Cartridge's own earlier run; the `want` values in `searches.json` that came from there agree with `reference-answers.json`.

## Fairness notes

- **Same caps.** Both systems run in Docker with `--cpus 4 --memory 16g --memory-swap 16g`, on the same instance
  type, the same volume and the same S3 bucket. (Loading Elasticsearch uses a 24 GB container with no CPU cap;
  nothing timed against Cartridge runs in that shape.)
- **No result caches.** Elasticsearch: `request_cache=false` on every search, and the node query cache disabled on
  every index. Cartridge: its result cache is switched off by environment variable (`CARTRIDGE_NO_RESULT_CACHE=1`,
  set with the other `CARTRIDGE_*` variables in `../lib/cart.sh`, as in our runs).
- **Cold start per chain.** A fresh server process and a dropped page cache before every chain, for both systems.
- **Per-search cap.** 60 seconds. The first search that exceeds it ends its chain, for both systems.
- **Elasticsearch's 5 inexact answers.** In `hot-es.log` 34 of 39 answers are exact. The other five (e1, e4, f1,
  g4, h4) are "top N" searches, run as a terms aggregation with Elasticsearch's default `shard_size`; with five
  shards that default can miss a key or return a slightly wrong count. They are timed as they ran at the
  default and marked `approx`. After each chain the runner (untimed) raises `shard_size` until the answer matches;
  exact answers needed `shard_size` 368 (e1), 544 (e4), 200 (f1), 92 (g4) and 46 (h4).
- **Cold uses the 35 searches both systems answer.** In `cold-cart.log` three searches (e1, f1, g3) did not finish
  within 60 s, and the rest of their chains did not run. The 63 s and the 290 s sum the same 35 searches. The set
  includes Elasticsearch's `approx` answers.
- **The field index.** Cartridge's hot 11.0 s and warm 9.9 s use a field index (`<cart>.facets`) built from the same raw
  files; searches on status, client IP, method, path and protocol use it when it is next to a local cart. Without it the
  hot run is 16.3 s (`speed/hot-cart-no-field-index.log`), against Elasticsearch's 11.5 s. The cold run never uses it.
  Set `SIDECAR=0` to run `20-speed.sh` without it. Warm first answers include copying it. The published size
  includes the field index.
- **Press flags (superseded).** The earlier stored press runs used one more press option than the
  command shown in `10-size.sh`. Their cart size (3.24 GB, 3,237,744,683 bytes) is superseded by the 2026-10-26
  verification run: default flags, cart 2.12 GB (2,118,597,954 bytes) plus field index 0.860 GB (859,679,545 bytes),
  total 2.98 GB (2,978,277,499 bytes). The stored logs are kept as they were.
- **Expected answers (superseded).** The earlier expected answers were Cartridge's own answers on a local copy
  (only the 403/404/500 totals and the line-search match sets came from the raw file). The 2026-10-26 run replaces
  that: every expected answer is computed from the raw text by `reference.py` (48 of 48 runs matched).
- **Two Elasticsearch standard sizes.**
  - 22.5 GB: an r7i load on 2026-10-21.
  - 18.7 GB: a restore of the snapshot the speed runs used (loaded on a c7i on 2026-10-05, 19.1 GB stored).
  - The cause of the difference is not recorded.
- **What the harness did differently.** `run_searches.py` is a condensed Python port of the shell harness that
  produced the stored logs (same canonical forms, caps, cache settings and cold start per chain), so a rerun is
  not byte-identical to the stored runs.

## Not recorded

- SHA-256 of each downloaded file: not recorded when the data was first fetched. `00-data.sh` checks the published
  byte sizes, the line count and the oracle counts, and prints the SHA-256 of what it downloaded so you can pin them.
- The cause of the difference between the two Elasticsearch standard sizes (above).
