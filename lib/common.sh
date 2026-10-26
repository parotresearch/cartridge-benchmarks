# shellcheck shell=bash disable=SC2034
# Shared setup for every storage/<dataset>/run.sh. Source it; do not run it.
set -euo pipefail

ES_URL=http://127.0.0.1:9200
ES_VERSION=9.5.5
ES_IMAGE=docker.elastic.co/elasticsearch/elasticsearch:$ES_VERSION
OS_VERSION=3.9.0
OS_IMAGE=opensearchproject/opensearch:$OS_VERSION

die() { echo "ERROR: $*" >&2; exit 1; }
log() { echo "[$(date -u +%H:%M:%S)] $*"; }

need() {  # need CMD...: fail before any work if a tool is missing
  local c
  for c in "$@"; do command -v "$c" >/dev/null || die "missing required command '$c'"; done
}

# the repo's lib/ directory
LIB=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
