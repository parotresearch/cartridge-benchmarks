# shellcheck shell=bash
# shellcheck disable=SC2034  # variables are used by the scripts that source this file
# Settings and small helpers shared by every script in speed/. Source it; do not run it.
# Every value can be overridden from the environment.

: "${BUCKET:?set BUCKET to an S3 bucket you own, in the same region as this machine}"
: "${AWS_REGION:=us-east-2}"
export AWS_REGION AWS_DEFAULT_REGION=$AWS_REGION

# Where raw logs, carts and Elasticsearch data live on this machine.
: "${WORK:=$HOME/cartridge-benchmarks-work}"
RAW=$WORK/raw
CART_DIR=$WORK/carts
ES_DATA=$WORK/es-data
RESULTS=${RESULTS:-$WORK/results}

# Versions and settings used for every stored number.
: "${ES_VERSION:=9.5.4}"
: "${RALLY_VERSION:=2.13.0}"
: "${OS_VERSION:=3.9.0}"
: "${OSB_VERSION:=2.4.0}"
: "${OSB_WORKLOADS_SHA:=a60ab39b5fe80b7b6e2413db0aee2939d6407edb}"
: "${CAP_CPUS:=4}"          # both systems are capped at 4 CPUs ...
: "${CAP_MEM:=16g}"         # ... and 16 GB while they answer searches
: "${ES_INGEST_MEM:=24g}"   # loading and merging is not timed against Cartridge: a bigger container
: "${CAP_S:=60}"            # a search that takes longer than this is recorded as a timeout
: "${CART_IMAGE:=ubuntu:24.04}"

# The corpus: the 1998 World Cup web logs, 7 weekly files, from Elastic's public Rally track store.
RALLY_BASE=https://rally-tracks.elastic.co/http_logs
WEEKS=(181998 191998 201998 211998 221998 231998 241998)
DOCS=247249096
RAW_BYTES=23475280341

ES_REPO=s3-aws
ES_SNAPSHOT_PATH=es-snapshots
ES_SNAPSHOT=frozen1-history-merged
CART_KEY=http_logs_attr3-v4.cart
ES_NAME=es
CART_NAME=cart

HERE_LIB=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
HTTP_LOGS=$(cd "$HERE_LIB/../http_logs" && pwd)

log() { printf '%s %s\n' "$(date -u +%T)" "$*" >&2; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null || die "$1 is required on this machine: $2"; }
ms_since() { echo $(( ($(date +%s%N) - $1) / 1000000 )); }
drop_caches() { sync; echo 3 | sudo tee /proc/sys/vm/drop_caches >/dev/null; }
