#!/usr/bin/env bash
set -euo pipefail

if [ "${DEBUG:-false}" = "true" ]; then
  set -x
fi

VERSION=""
LOCAL_BUILD=false
NO_CACHE_ARG=""
APP_FILTER="all"
DOCKER_ORG="${DOCKER_ORG:-networknt}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${SCRIPT_DIR}"
WORKSPACE_ROOT="$(cd "${REPO_ROOT}/.." && pwd)"

APPS=(
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
  echo "    build.sh [VERSION] [-l|--local] [--no-cache] [--app APP] [--image-org ORG]"
  echo " "
  echo "    where [VERSION] is the Docker image version to build and publish"
  echo "          [-l|--local] builds images locally without pushing to Docker Hub"
  echo "          [--no-cache] builds images without using the Docker build cache"
  echo "          [--app APP] builds one app instead of all apps"
  echo "          [--image-org ORG] overrides the Docker Hub namespace"
  echo " "
  echo "    apps:"
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

  echo "Building Docker image ${image_name}:${VERSION}"
  docker build ${NO_CACHE_ARG} \
    --build-arg APP_NAME="${app_name}" \
    --build-arg APP_DIR="${app_dir}" \
    --build-arg PORT="${port}" \
    -t "${image_name}:${VERSION}" \
    -t "${image_name}:latest" \
    -f "${REPO_ROOT}/docker/Dockerfile" \
    "${WORKSPACE_ROOT}"

  if $LOCAL_BUILD; then
    echo "Skipping Docker Hub publish for ${image_name} due to local build flag"
  else
    echo "Pushing ${image_name}:${VERSION} and ${image_name}:latest"
    docker push "${image_name}:${VERSION}"
    docker push "${image_name}:latest"
  fi
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
      NO_CACHE_ARG="--no-cache"
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

matched=false
for app_spec in "${APPS[@]}"; do
  IFS=":" read -r app_name app_dir port <<<"${app_spec}"
  if selected_app "$app_name"; then
    matched=true
    build_app "$app_name" "$app_dir" "$port"
  fi
done

if ! $matched; then
  fail "Unknown app: ${APP_FILTER}"
fi

echo "Docker build completed for version ${VERSION}"
