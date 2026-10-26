#!/usr/bin/env bash
# CockroachDB JSON logs (Zenodo 10516387): stored size in Elasticsearch standard, Elasticsearch logsdb, OpenSearch default and Cartridge.
#
# (The stored Elasticsearch and Cartridge sizes for this dataset were measured on a c7i.4xlarge, 16 vCPU / 30 GB; only the OpenSearch size came from the r7i.4xlarge. Stored size does not depend on the box.)
# Hardware used for the numbers in README.md: one AWS r7i.4xlarge (16 vCPU, 128 GB RAM), on demand, Ubuntu 24.04, no other load.
# Needs: Docker (run through sudo), curl, jq, python3, uv, ~150 GB of free disk. Network access to Zenodo, Docker Hub and cartridge.app.
# A press spends Cartridge pressing credit (25 GB free) and asks you to confirm; PRESS_YES=1 answers yes.
#
# Usage: storage/cockroachdb/run.sh        (work files go to ./work-cockroachdb, override with WORK=...)
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
LIB=$HERE/../../lib
# shellcheck source=../../lib/common.sh
source "$LIB/common.sh"
# shellcheck source=../../lib/data.sh
source "$LIB/data.sh"
# shellcheck source=../../lib/es.sh
source "$LIB/es.sh"
# shellcheck source=../../lib/os.sh
source "$LIB/os.sh"
# shellcheck source=../../lib/cartridge.sh
source "$LIB/cartridge.sh"
# shellcheck source=../../lib/report.sh
source "$LIB/report.sh"

need docker curl jq python3 uv tar
press_confirm
mkdir -p "${WORK:=$PWD/work-cockroachdb}"; cd "$WORK"
report_init

RAW_BYTES=10506623721
LINES=16520377

log "1. download cockroachdb.tar.gz (Zenodo 10516387) and verify its SHA-256, then unpack the one NDJSON file"
fetch_verify "https://zenodo.org/records/10516387/files/cockroachdb.tar.gz?download=1" \
  9b6913ae481e387090dc3fbc37e3b699dc634496af982962ca4bd946b482470d cockroachdb.tar.gz
mkdir -p raw
tar -xzf cockroachdb.tar.gz -C raw
F=raw/cockroachdb/cockroach.node1.log
expect_input "$F" "$RAW_BYTES" "$LINES"

log "2. Elasticsearch $ES_VERSION, standard mode: one shard, no replica, @timestamp mapped as date (epoch_millis), every other field dynamic"
es_up
es PUT /cr-standard '{"settings":{"index":{"number_of_shards":1,"number_of_replicas":0,"mode":"standard"}},"mappings":{"properties":{"@timestamp":{"type":"date","format":"epoch_millis"}}}}' >/dev/null
python3 -I "$HERE/load.py" "$F" cr-standard index load-standard.json   # batches of 4,000 lines, 4 threads; @timestamp spliced from "timestamp"
es_refresh cr-standard
es_forcemerge cr-standard                                              # one segment
[[ $(es_count cr-standard) == "$LINES" ]] || die "cr-standard does not hold $LINES documents"
ES_STD=$(es_store_bytes cr-standard)
report_row "Elasticsearch $ES_VERSION standard" "$ES_STD"

log "3. Elasticsearch $ES_VERSION logsdb: the stock logs-cockroach-default data stream (created by the first bulk request)"
python3 -I "$HERE/load.py" "$F" logs-cockroach-default create load-logsdb.json
es_refresh logs-cockroach-default
es_forcemerge logs-cockroach-default
[[ $(es GET '/logs-cockroach-default/_settings?flat_settings=true&include_defaults=true' | jq -r '[.[] | (.settings["index.mode"] // .defaults["index.mode"])] | unique | join(",")') == logsdb ]] || die "the data stream is not in logsdb mode"
[[ $(es_count logs-cockroach-default) == "$LINES" ]] || die "logs-cockroach-default does not hold $LINES documents"
ES_LOGSDB=$(es_store_bytes '.ds-logs-cockroach-default*')
report_row "Elasticsearch $ES_VERSION logsdb" "$ES_LOGSDB"

log "4. OpenSearch $OS_VERSION, default settings, fresh node: explicit @timestamp mapping, other fields dynamic; batches of 4,000 lines, 4 workers"
os_up
es PUT /cr-os "$(cat "$HERE/opensearch-mapping.json")" >/dev/null
uv run --script "$LIB/load_os.py" "$F" cr-os load-os.json --mode cr --batch 4000 --workers 4
es_refresh cr-os
[[ $(es_count cr-os) == "$LINES" ]] || die "cr-os does not hold $LINES documents"
OS_STORE=$(os_measure cr-os "$LINES")                                  # force-merge, refresh, flush, settle
report_row "OpenSearch $OS_VERSION default" "$OS_STORE"
os_stop

log "5. Cartridge: install, then press the NDJSON with --gron at the default level (2) and at --level 1, one after the other"
cartridge_install
cartpress press "$F" --gron -o cr-L2.cart -y
cartpress press "$F" --gron -o cr-L1.cart -y --level 1
report_row "Cartridge level 2 (default)" "$(stat -c %s cr-L2.cart)"
report_row "Cartridge level 1" "$(stat -c %s cr-L1.cart)"

log "6. results (the stored run's numbers are in README.md)"
report_table "$RAW_BYTES"
