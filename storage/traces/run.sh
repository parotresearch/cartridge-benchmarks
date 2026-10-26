#!/usr/bin/env bash
# Alibaba microservice call-graph traces (cluster-trace-microservices-v2022, chunks 0-3) converted to OpenTelemetry spans:
# stored size in Elasticsearch (stock OTel traces template in standard mode and in its default logsdb mode), OpenSearch default and Cartridge.
#
# Hardware used for the numbers in README.md: one AWS r7i.4xlarge (16 vCPU, 128 GB RAM), on demand, Ubuntu 24.04, no other load.
# Needs: Docker (run through sudo), curl, jq, python3, uv, ~250 GB of free disk. Network access to aliyuncs.com, Docker Hub and cartridge.app.
#
# Usage: storage/traces/run.sh        (work files go to ./work-traces, override with WORK=...)
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

need docker curl jq python3 uv tar sha256sum
mkdir -p "${WORK:=$PWD/work-traces}"; cd "$WORK"
report_init

RAW_BYTES=19744374361   # 51,982,824 spans, one JSON object per line
SPANS_N=51982824
BASE=https://aliopentrace.oss-cn-beijing.aliyuncs.com/v2022MicroservicesTraces/CallGraph
STOCK=traces-alibaba-cg2022.otel-default       # stock OTel traces template (index.mode logsdb on this release)
STD=traces-alibaba-cg2022.otelstd-default      # the same template with index.mode=standard

log "1. download CallGraph_0..3.tar.gz from the public Alibaba trace archive and verify each SHA-256"
fetch_verify "$BASE/CallGraph_0.tar.gz" df1fff9628d9e993440b2826912aa37e71d37cbddf9b9249389b2b71afbad2f9 CallGraph_0.tar.gz
fetch_verify "$BASE/CallGraph_1.tar.gz" 09c1b0939b0537c6705291df13fc269230f5ff0b1e7963e13b3e5200c1b76176 CallGraph_1.tar.gz
fetch_verify "$BASE/CallGraph_2.tar.gz" aa8e56392d8b74eb8fbccd7fdf6172b45ae081072f2902150c784cf09bd3cc11 CallGraph_2.tar.gz
fetch_verify "$BASE/CallGraph_3.tar.gz" 2c2b3af818090e735e5f455a668eb539d932ca31d8e6e33fb0534a42bb1a22ed CallGraph_3.tar.gz

log "1b. convert each chunk to OpenTelemetry span NDJSON (4 chunks in parallel), concatenate in chunk order, verify the SHA-256 of the result"
cp "$HERE/alibaba_callgraph_to_otel.py" .
uv run --script alibaba_callgraph_to_otel.py --help >/dev/null    # create the script's environment once, so the parallel runs do not race on it
PIDS=()
for i in 0 1 2 3; do
  ( tar -xzOf "CallGraph_$i.tar.gz" | uv run --script alibaba_callgraph_to_otel.py > "part_$i.ndjson" ) & PIDS+=($!)
done
for p in "${PIDS[@]}"; do wait "$p" || die "a chunk conversion failed"; done
cat part_0.ndjson part_1.ndjson part_2.ndjson part_3.ndjson > spans.ndjson
rm -f part_?.ndjson
echo "2d979fbeae1a709fc6138e23b7a824b40524b3e092649988e795c9ccdc41a5b5  spans.ndjson" | sha256sum -c - || die "spans.ndjson differs from the file the stored numbers were measured on"
expect_input spans.ndjson "$RAW_BYTES" "$SPANS_N"

log "2. Elasticsearch $ES_VERSION standard: the stock OTel traces template with only index.mode=standard, fresh node"
es_up
es PUT /_index_template/traces-otelstd "$(es GET /_index_template/traces-otel@template | jq -c '.index_templates[0].index_template
  | del(.created_date, .created_date_millis, .modified_date, .modified_date_millis)
  | .index_patterns = ["traces-*.otelstd-*"] | .priority = (.priority + 1) | .template.settings.index.mode = "standard"')" >/dev/null
uv run --script "$HERE/load_es.py" spans.ndjson "$STD" load-standard.json   # official Python client, batches of 5,000, 8 workers
es_refresh "$STD"
[[ $(es_count "$STD") == "$SPANS_N" ]] || die "$STD does not hold $SPANS_N spans"
es_forcemerge "$STD"                                                       # one segment
ES_STD=$(es_store_bytes ".ds-$STD*")
report_row "Elasticsearch $ES_VERSION standard (stock OTel template)" "$ES_STD"

log "3. Elasticsearch $ES_VERSION logsdb: the stock traces-otel@template stream, fresh node"
es_up
uv run --script "$HERE/load_es.py" spans.ndjson "$STOCK" load-stock.json
es_refresh "$STOCK"
[[ $(es_count "$STOCK") == "$SPANS_N" ]] || die "$STOCK does not hold $SPANS_N spans"
[[ $(es GET "/$STOCK/_settings?flat_settings=true&include_defaults=true" | jq -r '[.[] | (.settings["index.mode"] // .defaults["index.mode"])] | unique | join(",")') == logsdb ]] || die "the stock stream is not in logsdb mode"
es_forcemerge "$STOCK"
ES_LOGSDB=$(es_store_bytes ".ds-$STOCK*")
report_row "Elasticsearch $ES_VERSION stock OTel stream (logsdb)" "$ES_LOGSDB"

log "4. OpenSearch $OS_VERSION, default settings, fresh node: explicit strict mapping, attributes as flat_object; batches of 5,000, 8 workers"
os_up
es PUT /traces-os "$(cat "$HERE/opensearch-mapping.json")" >/dev/null
uv run --script "$LIB/load_os.py" spans.ndjson traces-os load-os.json --mode raw --batch 5000 --workers 8
es_refresh traces-os
[[ $(es_count traces-os) == "$SPANS_N" ]] || die "traces-os does not hold $SPANS_N spans"
OS_STORE=$(os_measure traces-os "$SPANS_N")                                # force-merge, refresh, flush, settle
report_row "OpenSearch $OS_VERSION default (flat_object attributes)" "$OS_STORE"
os_stop

log "5. Cartridge: install, then press the span NDJSON with --gron at the default level (2) and at --level 1"
cartridge_install
# Each press asks for confirmation and uses Cartridge pressing credit (25 GB free).
cartpress press spans.ndjson --gron -o traces-L2.cart
cartpress press spans.ndjson --gron -o traces-L1.cart --level 1
report_row "Cartridge level 2 (default)" "$(stat -c %s traces-L2.cart)"
report_row "Cartridge level 1" "$(stat -c %s traces-L1.cart)"

log "6. results (the stored run's numbers are in README.md)"
report_table "$RAW_BYTES"
