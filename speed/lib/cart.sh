# shellcheck shell=bash
# Cartridge helpers. Source env.sh first.
# The cartridge service runs in a Docker container capped at the same 4 CPUs and 16 GB as Elasticsearch.
# Install: curl -sSf https://cartridge.app/install | sh   (puts `cartridge` and `cartpress` on PATH)

CART_BIN=${CART_BIN:-$(command -v cartridge || true)}
d() { sudo docker "$@"; }

cart_stop() { if d inspect "$CART_NAME" >/dev/null 2>&1; then d rm -f "$CART_NAME" >/dev/null; fi; }

# cart_container [DATA_DIR]: a fresh container. Result caches are off so every search does real work.
cart_container() {
  [[ -x $CART_BIN ]] || die "cartridge is not installed: curl -sSf https://cartridge.app/install | sh"
  cart_stop
  d run -d --init --name "$CART_NAME" --cpus "$CAP_CPUS" --memory "$CAP_MEM" --memory-swap "$CAP_MEM" \
    -v "$(dirname "$(readlink -f "$CART_BIN")"):/opt/bin:ro" ${1:+-v "$1:/data:ro"} \
    -e HOME=/root -e "AWS_REGION=$AWS_REGION" -e "AWS_DEFAULT_REGION=$AWS_REGION" \
    -e CARTRIDGE_READER_IDLE=off -e CARTRIDGE_RANGE_GRANULE_BYTES=exact -e CARTRIDGE_NO_RESULT_CACHE=1 \
    "$CART_IMAGE" sleep infinity >/dev/null
}
# cart_service_start [TARGET]: with no target the service starts empty and opens the cart on the first search.
cart_service_start() {
  timeout -s KILL 60 sudo docker exec "$CART_NAME" /opt/bin/cartridge service start ${1:+"$1"} >/dev/null \
    || die "cartridge service start ${1:-} failed"
}

# The cart (and, when SIDECAR=1, the field sidecar next to it as <cart>.facets) copied from S3 to local disk.
cart_copy() {  # cart_copy DEST
  mkdir -p "$(dirname "$1")"
  aws s3 cp "s3://$BUCKET/$CART_KEY" "$1" --only-show-errors
  if [[ ${SIDECAR:-1} == 1 ]]; then aws s3 cp "s3://$BUCKET/$CART_KEY.facets" "$1.facets" --only-show-errors; fi
}
cart_local_rm() { rm -f "$1" "$1.facets"; }
