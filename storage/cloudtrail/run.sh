#!/usr/bin/env bash
# CloudTrail audit logs from flaws.cloud: stored size in Elasticsearch (flattened mapping, flattened + logsdb, stock logs data stream),
# OpenSearch default and Cartridge.
# (The stored Elasticsearch and Cartridge sizes for this dataset were measured on a c7i.4xlarge, 16 vCPU / 30 GB; only the OpenSearch size came from the r7i.4xlarge. Stored size does not depend on the box.)
#
# Hardware used for the numbers in README.md: one AWS r7i.4xlarge (16 vCPU, 128 GB RAM), on demand, Ubuntu 24.04, no other load.
# Needs: Docker (run through sudo), curl, jq, gron, python3, uv, ~100 GB of free disk. Network access to summitroute.com, Docker Hub and cartridge.app.
# A press spends Cartridge pressing credit (25 GB free) and asks you to confirm; PRESS_YES=1 answers yes.
#
# Usage: storage/cloudtrail/run.sh        (work files go to ./work-cloudtrail, override with WORK=...)
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

need docker curl jq gron python3 uv tar zcat awk sed
press_confirm
mkdir -p "${WORK:=$PWD/work-cloudtrail}"; cd "$WORK"
report_init

RAW_BYTES=2389223172   # one event per line
EVENTS=1939207

log "1. download flaws_cloudtrail_logs.tar and verify its SHA-256; 20 gzip files, each {\"Records\":[...]}"
fetch_verify "https://summitroute.com/downloads/flaws_cloudtrail_logs.tar" \
  f26c2b8da56bb00d695a57f00f86208117582b9216bb52424d68e718ca2a96aa flaws_cloudtrail_logs.tar
mkdir -p src
tar -xf flaws_cloudtrail_logs.tar -C src
mapfile -t GZ < <(find src -name 'flaws_cloudtrail*.json.gz' | sort)
(( ${#GZ[@]} == 20 )) || die "expected 20 flaws_cloudtrail*.json.gz files, found ${#GZ[@]}"
[[ $(du -cb "${GZ[@]}" | tail -1 | cut -f1) == 251670186 ]] || die "the gzip files are not 251,670,186 bytes in total"

log "1b. one event per line"
for f in "${GZ[@]}"; do zcat "$f" | jq -c '.Records[]'; done > events.ndjson
expect_input events.ndjson "$RAW_BYTES" "$EVENTS"

log "2. Elasticsearch $ES_VERSION standard mode: requestParameters, responseElements, additionalEventData, serviceEventDetails mapped as flattened, the rest dynamic"
es_up_8g_heap                                                        # 8 GB heap, host networking, GeoIP downloader off
python3 -I "$HERE/es_load.py" ct-b B events.ndjson load-b.json       # batches of 2,000 events; rejected events are counted, never retried
es_forcemerge ct-b
es_refresh ct-b
ES_STD=$(es_store_bytes ct-b)
echo "ct-b: $(jq -c '{indexed, rejected}' load-b.json)"
report_row "Elasticsearch $ES_VERSION standard (flattened fields)" "$ES_STD"

log "3. Elasticsearch $ES_VERSION logsdb: the same mapping plus index.mode=logsdb (eventTime is copied to @timestamp)"
python3 -I "$HERE/es_load.py" ct-c C events.ndjson load-c.json
es_forcemerge ct-c
es_refresh ct-c
ES_LOGSDB=$(es_store_bytes ct-c)
echo "ct-c: $(jq -c '{indexed, rejected}' load-c.json)"
report_row "Elasticsearch $ES_VERSION logsdb (flattened fields)" "$ES_LOGSDB"

log "3b. Elasticsearch $ES_VERSION stock logs-cloudtrail-default data stream: no custom mapping or settings (eventTime copied to @timestamp)"
python3 -I "$HERE/es_load_datastream.py" events.ndjson load-d.json   # merges to one segment itself
ES_STOCK=$(es_store_bytes '.ds-logs-cloudtrail-default-*')
echo "stock stream: $(jq -c '{indexed, rejected, docs_with_ignored}' load-d.json), searchable now: $(es_count logs-cloudtrail-default)"
report_row "Elasticsearch $ES_VERSION stock logs data stream" "$ES_STOCK"

log "4. OpenSearch $OS_VERSION, default settings, fresh node: the four fields as flat_object, the rest dynamic; batches of 2,000, 1 worker"
os_up
es PUT /ct-os "$(cat "$HERE/opensearch-mapping.json")" >/dev/null
uv run --script "$LIB/load_os.py" events.ndjson ct-os load-os.json --mode raw --batch 2000 --workers 1 --allow-rejections
es_refresh ct-os
OS_DOCS=$(jq -er .indexed load-os.json)
[[ $(es_count ct-os) == "$OS_DOCS" ]] || die "ct-os does not hold the $OS_DOCS documents the loader reports"
echo "ct-os: $(jq -c '{indexed, errors}' load-os.json)"
OS_STORE=$(os_measure ct-os "$OS_DOCS")                              # force-merge, refresh, flush, settle
report_row "OpenSearch $OS_VERSION default (flat_object fields)" "$OS_STORE"
os_stop

log "5. Cartridge: install, flatten the events with gron into one paragraph per event, press at level 2 (default) and --level 1"
cartridge_install
export LC_ALL=C
gron --stream events.ndjson | tail -n +2 | awk '/^json\[[0-9]+\] = \{\};$/ && NR>1 {print ""} {print}' | sed -E 's/^json\[[0-9]+\]/json/' > events.gron.txt
cartpress press events.gron.txt --text-segment paragraph -o ct-L2.cart -y
cartpress press events.gron.txt --text-segment paragraph -o ct-L1.cart -y --level 1
report_row "Cartridge level 2 (default)" "$(stat -c %s ct-L2.cart)"
report_row "Cartridge level 1" "$(stat -c %s ct-L1.cart)"

log "6. results (the stored run's numbers are in README.md)"
report_table "$RAW_BYTES"
