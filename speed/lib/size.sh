# shellcheck shell=bash
# Helpers for 10-size.sh. Source env.sh and es.sh first.

# Start from an empty Elasticsearch data directory.
es_wipe() { es_stop; sudo rm -rf "${ES_DATA:?}"/* ; }

# One Elasticsearch size pass: load with Rally, merge to one segment per shard, print the stored bytes.
#   es_size_pass NAME [LICENCE: basic|trial] [extra --track-params]
es_size_pass() {
  local name=$1 licence=${2:-basic} extra=${3:-} t0
  es_wipe; es_start ingest
  if [[ $licence == trial ]]; then es_trial; fi
  es_template; es_parsed_corpus
  t0=$SECONDS; es_rally_load "$extra"; echo "load name=$name wall_s=$((SECONDS - t0))"
  [[ $(es_count 'logs-history-*') == "$DOCS" ]] || die "$name: loaded index does not hold $DOCS documents"
  t0=$SECONDS; es_force_merge; echo "forcemerge name=$name wall_s=$((SECONDS - t0))"
  echo "RESULT name=$name store_bytes=$(es_store_bytes 'logs-history-*')"
}

# OpenSearch default, 3.9.0, security off, 24 GB container with a 12 GB heap, loaded with the OpenSearch Benchmark
# port of the same http_logs workload (same 8 clients x 5,000-document bulks, 5 shards, 0 replicas).
OS_URL=http://127.0.0.1:9200
os_stop() { if d inspect opensearch >/dev/null 2>&1; then d rm -f opensearch >/dev/null; fi; }
os_size_pass() {
  local wl=$WORK/opensearch-benchmark-workloads t0 w tid bytes
  need git "install git"; need uvx "install uv: https://docs.astral.sh/uv/"
  es_stop; os_stop; sudo rm -rf "${ES_DATA:?}"/*
  sudo sysctl -qw vm.max_map_count=262144
  d run -d --name opensearch --memory "$ES_INGEST_MEM" --memory-swap "$ES_INGEST_MEM" --ulimit nofile=65535:65535 \
    -p 127.0.0.1:9200:9200 -e discovery.type=single-node -e DISABLE_SECURITY_PLUGIN=true \
    -e DISABLE_INSTALL_DEMO_CONFIG=true -e OPENSEARCH_JAVA_OPTS="-Xms12g -Xmx12g" \
    -v "$ES_DATA:/usr/share/opensearch/data" "opensearchproject/opensearch:$OS_VERSION" >/dev/null
  local _
  for _ in $(seq 120); do
    if curl -fsS "$OS_URL/_cluster/health?wait_for_status=yellow&timeout=1s" >/dev/null 2>&1; then break; fi
    sleep 2
  done
  [[ -d $wl ]] || git clone -q https://github.com/opensearch-project/opensearch-benchmark-workloads "$wl"
  git -C "$wl" checkout -q "$OSB_WORKLOADS_SHA"
  es_parsed_corpus
  mkdir -p "$HOME/.benchmark/benchmarks/data"; ln -sfn "$RALLY_DATA" "$HOME/.benchmark/benchmarks/data/http_logs"
  t0=$SECONDS
  uvx --python 3.12 --from "opensearch-benchmark==$OSB_VERSION" opensearch-benchmark run \
    --workload-path="$wl/http_logs" --test-procedure=append-no-conflicts-index-only --pipeline=benchmark-only \
    --target-hosts=127.0.0.1:9200 --client-options="use_ssl:false,verify_certs:false,timeout:240" --offline \
    --exclude-tasks="type:force-merge,refresh-after-force-merge,wait-until-merges-finish" \
    --workload-params="number_of_shards:5,number_of_replicas:0,bulk_size:5000,bulk_indexing_clients:8" \
    --on-error=abort --kill-running-processes
  echo "load name=opensearch-default wall_s=$((SECONDS - t0))"
  # merge each index to one segment, timed per index
  for w in $(curl -fsS "$OS_URL/_cat/indices/logs-*?h=index" ); do
    t0=$SECONDS
    tid=$(curl -fsS -X POST "$OS_URL/$w/_forcemerge?max_num_segments=1&wait_for_completion=false" | jq -er .task)
    until [[ $(curl -fsS "$OS_URL/_tasks/$tid" | jq -r .completed) == true ]]; do sleep 5; done
    echo "forcemerge index=$w wall_s=$((SECONDS - t0))"
  done
  bytes=$(curl -fsS "$OS_URL/_cat/indices/logs-*?bytes=b&format=json&h=pri.store.size" | jq 'map(."pri.store.size" | tonumber) | add')
  echo "RESULT name=opensearch-default store_bytes=$bytes"
  os_stop
}

# Cartridge: press the 7 raw week files, then build the field sidecar next to the cart. Prints the byte sizes.
# Every step is checked: a failed command, a missing or empty output file stops the run (these functions are
# called under `||`, where `set -e` does not apply, so the checks are explicit).
cart_press() {
  need cartpress "curl -sSf https://cartridge.app/install | sh   (cartpress needs your account's pressing credit and asks you to confirm)"
  mkdir -p "$CART_DIR"
  local files=() w t0
  for w in "${WEEKS[@]}"; do files+=("$RAW/access-$w.log"); [[ -s $RAW/access-$w.log ]] || die "missing raw file $RAW/access-$w.log: run 00-data.sh"; done
  rm -f "$CART_DIR/$CART_KEY" "$CART_DIR/$CART_KEY.facets"
  t0=$SECONDS
  # --store-only proto: the press indexes method, proto and status; proto is not kept by default, and the index needs it stored.
  cartpress press "${files[@]}" -q --log -j 4 --index method:dimension,proto:dimension,status:dimension --store-only proto -o "$CART_DIR/$CART_KEY" \
    || die "cartpress failed"
  [[ -s $CART_DIR/$CART_KEY ]] || die "cartpress exited 0 but wrote no cart: $CART_DIR/$CART_KEY"
  echo "cartpress wall_s=$((SECONDS - t0))"
  echo "RESULT name=cartridge cart_bytes=$(stat -c %s "$CART_DIR/$CART_KEY")"
}
cart_sidecar() {
  need cartridge "curl -sSf https://cartridge.app/install | sh"
  [[ -s $CART_DIR/$CART_KEY ]] || die "no cart to build the sidecar from: $CART_DIR/$CART_KEY"
  local src=$WORK/press-order i=0 w t0
  rm -rf "$src"; mkdir -p "$src"   # the seven files, linked in press order: --source takes a directory and reads it in name order
  for w in "${WEEKS[@]}"; do i=$((i + 1)); ln -s "$RAW/access-$w.log" "$src/$i-access-$w.log"; done
  t0=$SECONDS
  cartridge --no-service fields build "$CART_DIR/$CART_KEY" --source "$src" --fields ip,status,method,path,proto --json \
    || die "cartridge fields build failed"
  [[ -s $CART_DIR/$CART_KEY.facets ]] || die "fields build exited 0 but wrote no sidecar: $CART_DIR/$CART_KEY.facets"
  echo "fields-build wall_s=$((SECONDS - t0))"
  cartridge --no-service fields info "$CART_DIR/$CART_KEY" --json || die "fields info failed"
  cartridge --no-service fields verify "$CART_DIR/$CART_KEY" || die "fields verify failed"
  echo "RESULT name=cartridge-sidecar sidecar_bytes=$(stat -c %s "$CART_DIR/$CART_KEY.facets")"
}
cart_upload() {  # the cart and its sidecar, as two objects
  aws s3 cp "$CART_DIR/$CART_KEY" "s3://$BUCKET/$CART_KEY" --only-show-errors
  aws s3 cp "$CART_DIR/$CART_KEY.facets" "s3://$BUCKET/$CART_KEY.facets" --only-show-errors
}
