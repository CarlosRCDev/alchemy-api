#!/usr/bin/env bash
# Builds (and optionally pushes) one Docker image per database driver.
# Every variant includes async support; fastapi is always added by the Dockerfile.
#
# Usage (from any folder):
#   deployments/build.sh                       # build every variant locally
#   deployments/build.sh postgres sqlite       # only some variants
#   IMAGE=user/sqlalchemy-rest-api deployments/build.sh --push          # build and push to Docker Hub
#   IMAGE=user/sqlalchemy-rest-api PLATFORMS=linux/amd64,linux/arm64 deployments/build.sh --push
#
# Environment variables:
#   IMAGE      image name, "user/sqlalchemy-rest-api" to push to Docker Hub (default sqlalchemy-rest-api)
#   VERSION    version tag prefix (default: version in pyproject.toml)
#   PLATFORMS  multi architecture build with buildx, only with --push (e.g. linux/amd64,linux/arm64)
#   LATEST     "false" to not tag "all" as latest, e.g. for an old version (default true)
#
# Tags of each variant: IMAGE:<variant> and IMAGE:<version>-<variant>.
# "all" also gets IMAGE:<version> and IMAGE:latest (unless LATEST=false).
set -euo pipefail

. "$(dirname "${BASH_SOURCE[0]}")/variants.sh"
PLATFORMS="${PLATFORMS:-}"
PUSH=false

selected=()
for arg in "$@"; do
    case "$arg" in
        --push) PUSH=true ;;
        -h|--help) usage; exit 0 ;;
        -*) echo "Unknown option: $arg" >&2; usage >&2; exit 1 ;;
        *) check_variant "$arg"; selected+=("$arg") ;;
    esac
done
[[ ${#selected[@]} -eq 0 ]] && selected=("${ORDER[@]}")

if $PUSH; then
    require_hub_image
fi
if [[ -n "$PLATFORMS" ]] && ! $PUSH; then
    # A multi architecture image can not be loaded in the local docker, only pushed
    echo "PLATFORMS needs --push" >&2
    exit 1
fi

for variant in "${selected[@]}"; do
    mapfile -t names < <(image_tags "$variant")
    tags=()
    for name in "${names[@]}"; do
        tags+=(-t "$name")
    done
    echo "==> $variant (EXTRAS=${VARIANTS[$variant]})"
    if [[ -n "$PLATFORMS" ]]; then
        docker buildx build --platform "$PLATFORMS" --push \
            -f "$ROOT/deployments/Dockerfile" \
            --build-arg "EXTRAS=${VARIANTS[$variant]}" \
            "${tags[@]}" "$ROOT"
    else
        docker build \
            -f "$ROOT/deployments/Dockerfile" \
            --build-arg "EXTRAS=${VARIANTS[$variant]}" \
            "${tags[@]}" "$ROOT"
        if $PUSH; then
            "$ROOT/deployments/push.sh" "$variant"
        fi
    fi
done

echo "Done: ${selected[*]} ($IMAGE, version $VERSION)"
