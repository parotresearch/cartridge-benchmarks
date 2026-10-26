#!/usr/bin/env bash
# Search speed on the 39 http_logs searches, in three tiers, for Elasticsearch and Cartridge.
#
#   BUCKET=<your-bucket> ./20-speed.sh <arm>
#
# Arms (each writes $RESULTS/<arm>.log; run them on a c7i.4xlarge: 16 vCPU, 32 GiB, gp3 16000 IOPS / 1000 MB/s):
#   setup               load + merge Elasticsearch, snapshot it to S3, press Cartridge, build its sidecar, upload both
#   hot-es              data on local disk
#   hot-cart
#   warm-es-restore     data in S3; a fresh server restores it to local disk, searches start when the restore is done
#   warm-es-fullcopy    data in S3; a fresh server mounts it as a full copy and answers while the copy is made
#   warm-cart           data in S3; a fresh server copies it to local disk first, then answers
#   cold-es             answers straight from S3 (searchable snapshot, shared cache = 1/20 of the data)
#   cold-cart
#   all                 every arm above except setup
#
# Both systems are capped at 4 CPUs and 16 GB (docker --cpus 4 --memory 16g). Before every chain: a fresh server
# process and the page cache dropped, so no chain benefits from an earlier one. Result caches are off on both sides.
# Every search has a 60 s cap; the first search past it ends its chain. SIDECAR=0 runs Cartridge without the field sidecar.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=../lib/env.sh
source "$HERE/../lib/env.sh"
# shellcheck source=../lib/es.sh
source "$HERE/../lib/es.sh"
# shellcheck source=../lib/size.sh
source "$HERE/../lib/size.sh"
# shellcheck source=../lib/cart.sh
source "$HERE/../lib/cart.sh"

SIDECAR=${SIDECAR:-1}
export SIDECAR
RUN="uv run $HERE/../lib/run_searches.py"
CHAINS=$(jq -r '.chains[].id' "$HERE/searches.json")
FACETS_FLAG=(); if [[ $SIDECAR == 1 ]]; then FACETS_FLAG=(--facets); fi
mkdir -p "$RESULTS"

# search_es CHAIN INDEX [T0_NS]   |   search_cart CHAIN TARGET [T0_NS]: one chain, appended to the arm's log
search_es() { $RUN --system es --chain "$1" --index "$2" --cap "$CAP_S" ${3:+--t0-ns "$3"} >> "$LOG"; }
search_cart() { $RUN --system cart --chain "$1" --container "$CART_NAME" --target "$2" --cap "$CAP_S" "${FACETS_FLAG[@]}" ${3:+--t0-ns "$3"} >> "$LOG"; }

# ---- setup -----------------------------------------------------------------------------------------------------
arm_setup() {
  es_size_pass es-standard basic          # the Elasticsearch indices stay in place for the snapshot
  es_snapshot
  cart_press; cart_sidecar; cart_upload
}

# ---- hot: everything on local disk -----------------------------------------------------------------------------
arm_hot_es() {
  es_hot_restore
  local c; for c in $CHAINS; do es_start measure 1gb; es_wait_green 'logs-history-*'; drop_caches; search_es "$c" 'logs-history-*'; done
}
arm_hot_cart() {
  cart_local_rm "$CART_DIR/hot/$CART_KEY"; cart_copy "$CART_DIR/hot/$CART_KEY"      # copied once, then every chain
  local c; for c in $CHAINS; do
    cart_container "$CART_DIR"; cart_service_start "/data/hot/$CART_KEY"; drop_caches
    search_cart "$c" "/data/hot/$CART_KEY"
  done
}

# ---- warm: data in S3, a fresh server brings it local ----------------------------------------------------------
arm_warm_es() {  # arm_warm_es restore|fullcopy
  es_start measure 1gb; es_trial; es_repo ro
  local c t0; for c in $CHAINS; do
    es_start measure 1gb; es_wait_green '_all'; es_warm_clean; drop_caches
    t0=$(date +%s%N)                                       # clock starts: the server is up and has nothing local
    es_warm_settings; es_warm_open "$1"
    search_es "$c" 'warm-history-*' "$t0"
    es_warm_local_ok || die "$1: the copy was not fully local after chain $c"
    echo "WARM_CHECK A $c es mode=$1 ok=1 t_verified_local_ms=$(ms_since "$t0")" >> "$LOG"
  done
}
arm_warm_cart() {
  local c t0 copy_ms; for c in $CHAINS; do
    cart_local_rm "$CART_DIR/warm/$CART_KEY"
    cart_container "$CART_DIR"; cart_service_start; drop_caches    # the service is up, with no cart
    t0=$(date +%s%N)                                       # clock starts: copy from S3 to local disk, then search
    cart_copy "$CART_DIR/warm/$CART_KEY"
    copy_ms=$(ms_since "$t0")
    search_cart "$c" "/data/warm/$CART_KEY" "$t0"
    echo "WARM_COPY A $c cart-exact copy_ms=$copy_ms" >> "$LOG"
  done
}

# ---- cold: straight from S3 ------------------------------------------------------------------------------------
arm_cold_es() {
  es_cold_mount
  local c; for c in $CHAINS; do es_cold_restart; drop_caches; search_es "$c" 'frozen1-history-*'; done
}
arm_cold_cart() {
  local c; for c in $CHAINS; do
    cart_container; cart_service_start "s3://$BUCKET/$CART_KEY"; drop_caches   # no sidecar is read from S3
    FACETS_FLAG=(); search_cart "$c" "s3://$BUCKET/$CART_KEY"
  done
}

arm=${1:?usage: $0 <setup|hot-es|hot-cart|warm-es-restore|warm-es-fullcopy|warm-cart|cold-es|cold-cart|all>}
run_arm() {
  local suffix=field-sidecar; [[ $SIDECAR == 1 ]] || suffix=no-sidecar
  case $1 in
    hot-cart | warm-cart) LOG=$RESULTS/$1-$suffix.log ;;
    cold-es) LOG=$RESULTS/cold-es-frozen.log ;;
    *) LOG=$RESULTS/$1.log ;;
  esac
  : > "$LOG"
  log "arm $1 -> $LOG"
  case $1 in
    setup) arm_setup ;;
    hot-es) arm_hot_es ;;
    hot-cart) arm_hot_cart ;;
    warm-es-restore) arm_warm_es restore ;;
    warm-es-fullcopy) arm_warm_es fullcopy ;;
    warm-cart) arm_warm_cart ;;
    cold-es) arm_cold_es ;;
    cold-cart) arm_cold_cart ;;
    *) die "unknown arm '$1'" ;;
  esac
}
if [[ $arm == all ]]; then
  for a in hot-es hot-cart warm-es-restore warm-es-fullcopy warm-cart cold-es cold-cart; do run_arm "$a"; done
  uv run "$HERE/../lib/summarize.py" "$RESULTS"
else run_arm "$arm"; fi
