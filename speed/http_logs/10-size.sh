#!/usr/bin/env bash
# Stored size of the http_logs dataset in each system. Run on a machine with Docker, uv, the AWS CLI and jq
# (we used an r7i.4xlarge for Elasticsearch / OpenSearch / the press: 16 vCPU, 128 GiB).
#
#   BUCKET=<your-bucket> ./10-size.sh [es|logsdb|opensearch|cartridge|all]
#
# Each pass prints "RESULT name=... store_bytes=..." lines; they are also appended to $RESULTS/size.log.
# Run ./00-data.sh first. Versions, caps and paths live in ../lib/env.sh.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=../lib/env.sh
source "$HERE/../lib/env.sh"
# shellcheck source=../lib/es.sh
source "$HERE/../lib/es.sh"
# shellcheck source=../lib/size.sh
source "$HERE/../lib/size.sh"

mkdir -p "$RESULTS"
run() { "$@" 2>&1 | tee -a "$RESULTS/size.log"; }

# 1. Elasticsearch 9.5.4, standard index (what Elasticsearch gives you by default), free licence.
#    8 Rally clients x 5,000-document bulks, 5 shards, 0 replicas, then force-merge to one segment per shard.
pass_es() { run es_size_pass es-standard basic; }

# 2. Elasticsearch logsdb index mode.
#    free licence: logsdb keeps _source.   Enterprise (trial) licence: logsdb uses synthetic _source.
pass_logsdb() {
  run es_size_pass es-logsdb-free basic ",enable_logsdb:true"
  run es_size_pass es-logsdb-enterprise trial ",enable_logsdb:true"
}

# 3. OpenSearch 3.9.0, default settings.
pass_opensearch() { run os_size_pass; }

# 4. Cartridge: press the raw log files, then build the field sidecar. The sidecar is a separate file;
#    both are listed so the totals can be read either way.
pass_cartridge() {
  run cart_press
  run cart_sidecar
}

case ${1:-all} in
  es) pass_es ;;
  logsdb) pass_logsdb ;;
  opensearch) pass_opensearch ;;
  cartridge) pass_cartridge ;;
  all) pass_es; pass_logsdb; pass_opensearch; pass_cartridge ;;
  *) die "usage: $0 [es|logsdb|opensearch|cartridge|all]" ;;
esac
