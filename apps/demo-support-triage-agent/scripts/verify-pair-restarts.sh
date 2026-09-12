#!/usr/bin/env bash
# Deliberately restarts the supplied local demo containers; does not stop Portal.
set -euo pipefail
if [[ $# != 3 ]]; then
  echo "usage: $0 NAMESPACE_CONTAINER BACKEND_CONTAINER SIDECAR_CONTAINER" >&2
  exit 2
fi
namespace=$1
backend=$2
sidecar=$3
netns() { docker exec "$1" readlink /proc/1/ns/net; }
started() { docker inspect --format '{{.State.StartedAt}}' "$1"; }
ready() {
  local container=$1 url=$2
  for ((attempt=0; attempt<60; attempt++)); do
    if docker exec "$container" curl -fsS "$url" >/dev/null 2>&1; then return; fi
    sleep 1
  done
  echo "Container did not recover: $container" >&2
  return 1
}
check_network() {
  [[ $(netns "$namespace") == "$original_ns" ]]
  [[ $(netns "$backend") == "$original_ns" ]]
  [[ $(netns "$sidecar") == "$original_ns" ]]
  ready "$backend" http://127.0.0.1:9010/health/ready
  ready "$sidecar" http://127.0.0.1:8448/_a2a/ready
}
original_ns=$(netns "$namespace")
check_network
sidecar_started=$(started "$sidecar")
docker restart "$backend" >/dev/null
ready "$backend" http://127.0.0.1:9010/health/ready
check_network
[[ $(started "$sidecar") == "$sidecar_started" ]]
echo 'Backend restart preserved sidecar connectivity and namespace.'
# docker kill marks a container manually stopped and suppresses its restart
# policy. Signal the application from inside instead, without that daemon flag.
backend_started=$(started "$backend")
docker exec "$backend" /bin/sh -c 'kill -TERM 1'
for ((attempt=0; attempt<60; attempt++)); do
  [[ $(started "$backend") != "$backend_started" ]] && break
  sleep 1
done
[[ $(started "$backend") != "$backend_started" ]]
ready "$backend" http://127.0.0.1:9010/health/ready
check_network
[[ $(started "$sidecar") == "$sidecar_started" ]]
echo 'Automatic backend process-exit recovery preserved sidecar connectivity.'
backend_started=$(started "$backend")
docker restart "$sidecar" >/dev/null
ready "$sidecar" http://127.0.0.1:8448/_a2a/ready
check_network
[[ $(started "$backend") == "$backend_started" ]]
echo 'Sidecar restart preserved backend connectivity and namespace.'
