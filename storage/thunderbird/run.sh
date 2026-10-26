#!/usr/bin/env bash
# Thunderbird supercomputer syslog (first 10 GiB): stored size in Elasticsearch standard, Elasticsearch logsdb, OpenSearch default and Cartridge.
#
# (The stored Elasticsearch and Cartridge sizes for this dataset were measured on a c7i.4xlarge, 16 vCPU / 30 GB; only the OpenSearch size came from the r7i.4xlarge. Stored size does not depend on the box.)
# Hardware used for the numbers in README.md: one AWS r7i.4xlarge (16 vCPU, 128 GB RAM), on demand, Ubuntu 24.04, no other load.
# Needs: Docker (run through sudo), curl, jq, python3, uv, ~150 GB of free disk. Network access to Zenodo, Docker Hub and cartridge.app.
# A press spends Cartridge pressing credit (25 GB free) and asks you to confirm; PRESS_YES=1 answers yes.
#
# Usage: storage/thunderbird/run.sh        (work files go to ./work-thunderbird, override with WORK=...)
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
mkdir -p "${WORK:=$PWD/work-thunderbird}"; cd "$WORK"
report_init

RAW_BYTES=10737418238   # the first 10 GiB of Thunderbird.log, cut at a line boundary
LINES=69612888

log "1. download Thunderbird.tar.gz (Loghub, Zenodo 8196385) and verify its SHA-256"
fetch_verify "https://zenodo.org/records/8196385/files/Thunderbird.tar.gz?download=1" \
  228f8589b7cd569b727c5da654c647aa538dd3dd95541e675a40523c5fff37cf Thunderbird.tar.gz

log "1b. cut the first 10 GiB at a line boundary (tar gets SIGPIPE at the cut: expected)"
tar -xzOf Thunderbird.tar.gz Thunderbird.log | head -c 10737418240 > cut.raw || true
python3 -I - <<'PY'
import os
p = "cut.raw"; f = open(p, "r+b"); n = os.path.getsize(p); f.seek(max(0, n - 65536))
tail = f.read(); i = tail.rfind(b"\n"); f.truncate(n - len(tail) + i + 1)
PY
mv cut.raw tb10g.log
expect_input tb10g.log "$RAW_BYTES" "$LINES"

log "1c. copy with invalid UTF-8 replaced by U+FFFD (12 lines); Cartridge is pressed from this copy, the loaders decode with errors=replace"
python3 -I "$HERE/clean_utf8.py" tb10g.log tb10g.clean.log
[[ $(stat -c %s tb10g.clean.log) == 10737418350 ]] || die "tb10g.clean.log is not 10,737,418,350 bytes"

log "2. Elasticsearch $ES_VERSION, standard mode: one shard, no replica, refresh off, @timestamp date, message text"
es_up
es PUT /tb-standard '{"settings":{"index":{"mode":"standard","number_of_shards":1,"number_of_replicas":0,"refresh_interval":"-1"}},"mappings":{"properties":{"@timestamp":{"type":"date"},"message":{"type":"text"}}}}' >/dev/null
python3 -I "$HERE/bulk_load.py" tb10g.log tb-standard index 8      # batches of 20,000 lines, 8 workers
es_refresh tb-standard
es_forcemerge tb-standard                                           # one segment
[[ $(es_count tb-standard) == "$LINES" ]] || die "tb-standard does not hold $LINES documents"
ES_STD=$(es_store_bytes tb-standard)
report_row "Elasticsearch $ES_VERSION standard" "$ES_STD"

log "3. Elasticsearch $ES_VERSION logsdb: the stock logs-thunderbird-default data stream"
es PUT /_data_stream/logs-thunderbird-default >/dev/null
BACKING=$(es GET /_data_stream/logs-thunderbird-default | jq -r '.data_streams[0].indices[0].index_name')
es PUT "/$BACKING/_settings" '{"index":{"refresh_interval":"-1","number_of_replicas":0}}' >/dev/null
[[ $(es GET "/$BACKING/_settings?flat_settings=true&include_defaults=true" | jq -r '.[].settings["index.mode"] // .[].defaults["index.mode"]') == logsdb ]] || die "the data stream is not in logsdb mode"
python3 -I "$HERE/bulk_load.py" tb10g.log logs-thunderbird-default create 8
es_refresh logs-thunderbird-default
es_forcemerge logs-thunderbird-default
[[ $(es_count logs-thunderbird-default) == "$LINES" ]] || die "logs-thunderbird-default does not hold $LINES documents"
ES_LOGSDB=$(es_store_bytes logs-thunderbird-default)
report_row "Elasticsearch $ES_VERSION logsdb" "$ES_LOGSDB"

log "4. OpenSearch $OS_VERSION, default settings, fresh node: mapping-tb.json, batches of 20,000 lines, 8 workers"
os_up
es PUT /tb-os "$(cat "$HERE/opensearch-mapping.json")" >/dev/null
uv run --script "$LIB/load_os.py" tb10g.log tb-os load-os.json --mode tb --batch 20000 --workers 8
es_refresh tb-os
[[ $(es_count tb-os) == "$LINES" ]] || die "tb-os does not hold $LINES documents"
OS_STORE=$(os_measure tb-os "$LINES")                               # force-merge, refresh, flush, settle
report_row "OpenSearch $OS_VERSION default" "$OS_STORE"
os_stop

log "5. Cartridge: install, then press the cleaned copy at the default level (2) and at --level 1, one after the other"
cartridge_install
cartpress press tb10g.clean.log -o tb-L2.cart -y
cartpress press tb10g.clean.log -o tb-L1.cart -y --level 1
report_row "Cartridge level 2 (default)" "$(stat -c %s tb-L2.cart)"
report_row "Cartridge level 1" "$(stat -c %s tb-L1.cart)"

log "6. results (the stored run's numbers are in README.md)"
report_table "$RAW_BYTES"
