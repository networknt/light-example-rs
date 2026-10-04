#!/usr/bin/env bash
set -euo pipefail

if [ "${DEBUG:-false}" = "true" ]; then
  set -x
fi

VERSION=""
LOCAL_BUILD=false
NO_CACHE=false
CHANGED_ONLY=false
SKIP_LATEST=false
APP_FILTER="all"
DOCKER_ORG="${DOCKER_ORG:-networknt}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${SCRIPT_DIR}"
WORKSPACE_ROOT="$(cd "${REPO_ROOT}/.." && pwd)"

APPS=(
  "demo-support-triage-agent:apps/demo-support-triage-agent:9010"
  "demo-customer-profile-api:apps/demo-customer-profile-api:8085"
  "demo-insurance-claim-mcp-server:apps/demo-insurance-claim-mcp-server:8087"
  "demo-offer-decision-api:apps/demo-offer-decision-api:8086"
)

show_help() {
  local error="${1:-}"

  echo " "
  if [[ -n "$error" ]]; then
    echo "Error: ${error}"
    echo " "
  fi
  echo "    build.sh [VERSION] [-l|--local] [--changed] [--no-cache] [--skip-latest] [--app APP] [--image-org ORG]"
  echo " "
  echo "    where [VERSION] is the Docker image version to build and publish"
  echo "          [-l|--local] builds images locally without pushing to Docker Hub"
  echo "          [--no-cache] builds images without using the Docker build cache"
  echo "          [--changed] builds apps affected by uncommitted example or Fabric inputs"
  echo "          [--skip-latest] does not create or push latest tags"
  echo "          [--app APP] builds one app instead of all apps"
  echo "          [--image-org ORG] overrides the Docker Hub namespace"
  echo " "
  echo "    apps:"
  echo "          demo-support-triage-agent"
  echo "          demo-customer-profile-api"
  echo "          demo-insurance-claim-mcp-server"
  echo "          demo-offer-decision-api"
  echo " "
  echo "    examples:"
  echo "          ./build.sh 0.1.0"
  echo "          ./build.sh 0.1.0 --local"
  echo "          ./build.sh 0.1.0 --app demo-customer-profile-api"
  echo "          DOCKER_ORG=myorg ./build.sh 0.1.0 --local"
  echo " "
}

fail() {
  echo "Error: $*" >&2
  exit 1
}

require_command() {
  local command_name="$1"
  command -v "$command_name" >/dev/null 2>&1 || fail "Missing required command: ${command_name}"
}

selected_app() {
  local app_name="$1"
  [[ "$APP_FILTER" == "all" || "$APP_FILTER" == "$app_name" ]]
}

build_app() {
  local app_name="$1"
  local app_dir="$2"
  local port="$3"
  local image_name="${DOCKER_ORG}/${app_name}"
  local cache_id="warm"
  local -a docker_args=(build)
  if $NO_CACHE; then
    cache_id="${COLD_CACHE_PREFIX}-${app_name}"
    docker_args+=(--no-cache)
  fi
  docker_args+=(--build-arg "CARGO_CACHE_ID=${cache_id}"
    --build-arg "APP_NAME=${app_name}"
    --build-arg "APP_DIR=${app_dir}"
    --build-arg "PORT=${port}"
    -t "${image_name}:${VERSION}")
  if ! $SKIP_LATEST; then
    docker_args+=(-t "${image_name}:latest")
  fi
  docker_args+=(-f "${REPO_ROOT}/docker/Dockerfile" "${WORKSPACE_ROOT}")

  echo "Building Docker image ${image_name}:${VERSION}"
  DOCKER_BUILDKIT=1 docker "${docker_args[@]}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      show_help
      exit 0
      ;;
    -l|--local)
      LOCAL_BUILD=true
      shift
      ;;
    --no-cache)
      NO_CACHE=true
      shift
      ;;
    --changed)
      CHANGED_ONLY=true
      shift
      ;;
    --skip-latest)
      SKIP_LATEST=true
      shift
      ;;
    --app)
      [[ $# -ge 2 ]] || fail "--app requires an app name"
      APP_FILTER="$2"
      shift 2
      ;;
    --image-org)
      [[ $# -ge 2 ]] || fail "--image-org requires a Docker Hub namespace"
      DOCKER_ORG="$2"
      shift 2
      ;;
    -*)
      show_help "Invalid option: $1"
      exit 1
      ;;
    *)
      if [[ -z "$VERSION" ]]; then
        VERSION="$1"
      else
        show_help "Invalid option: $1"
        exit 1
      fi
      shift
      ;;
  esac
done

if [[ -z "$VERSION" ]]; then
  show_help "[VERSION] parameter is missing"
  exit 1
fi

require_command docker

BUILD_APPS=()
for app_spec in "${APPS[@]}"; do
  IFS=":" read -r app_name app_dir port <<<"${app_spec}"
  if selected_app "$app_name"; then
    BUILD_APPS+=("$app_spec")
  fi
done

if [[ ${#BUILD_APPS[@]} -eq 0 ]]; then
  fail "Unknown app: ${APP_FILTER}"
fi

if $CHANGED_ONLY; then
  require_command cargo
  require_command python3
  selector_args=(--root "$REPO_ROOT")
  for app_spec in "${BUILD_APPS[@]}"; do
    selector_args+=(--only "${app_spec%%:*}")
  done
  changed_output="$(python3 "$REPO_ROOT/scripts/select-changed-apps.py" "${selector_args[@]}")" \
    || fail "Unable to select changed apps"
  if [[ -z "$changed_output" ]]; then
    echo "No selected images are affected by uncommitted files; nothing to build or publish"
    exit 0
  fi
  selected=()
  for app_spec in "${BUILD_APPS[@]}"; do
    while IFS= read -r app_name; do
      if [[ "${app_spec%%:*}" == "$app_name" ]]; then
        selected+=("$app_spec")
        break
      fi
    done <<< "$changed_output"
  done
  BUILD_APPS=("${selected[@]}")
  echo "Changed image selection: ${changed_output//$'\n'/ }"
fi

# --no-cache must also avoid warm Cargo mounts. Prune only this invocation's
# uniquely named cold mounts, including on a failed build.
COLD_CACHE_PREFIX="cold-${BASHPID}-${RANDOM}"
if $NO_CACHE; then
  trap 'docker builder prune --force --filter "description~=${COLD_CACHE_PREFIX}-" >/dev/null 2>&1 || true' EXIT
fi

# Complete every selected build before publishing any part of the release.
for app_spec in "${BUILD_APPS[@]}"; do
  IFS=":" read -r app_name app_dir port <<< "$app_spec"
  build_app "$app_name" "$app_dir" "$port"
done

if $LOCAL_BUILD; then
  echo "Built all selected images locally; skipping Docker Hub publish"
  exit 0
fi

for app_spec in "${BUILD_APPS[@]}"; do
  image_name="${DOCKER_ORG}/${app_spec%%:*}"
  docker push "${image_name}:${VERSION}"
done
if ! $SKIP_LATEST; then
  for app_spec in "${BUILD_APPS[@]}"; do
    docker push "${DOCKER_ORG}/${app_spec%%:*}:latest"
  done
fi

echo "Docker build completed for version ${VERSION}"
