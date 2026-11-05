#!/usr/bin/env bash
# Pushes to Docker Hub the images already built locally by build.sh (no build here).
# Run "docker login" first.
#
# Usage (from any folder):
#   IMAGE=user/sqlalchemy-rest-api deployments/push.sh                    # every variant
#   IMAGE=user/sqlalchemy-rest-api deployments/push.sh postgres sqlite    # only some variants
#
# Environment variables (the same values used with build.sh):
#   IMAGE      "user/sqlalchemy-rest-api" (required, Docker Hub needs the user)
#   VERSION    version tag prefix (default: version in pyproject.toml)
#   LATEST     "false" to not push latest, e.g. for an old version (default true)
#
# Multi architecture images (build.sh with PLATFORMS) are pushed by build.sh itself.
set -euo pipefail

. "$(dirname "${BASH_SOURCE[0]}")/variants.sh"

selected=()
for arg in "$@"; do
    case "$arg" in
        -h|--help) usage; exit 0 ;;
        -*) echo "Unknown option: $arg" >&2; usage >&2; exit 1 ;;
        *) check_variant "$arg"; selected+=("$arg") ;;
    esac
done
[[ ${#selected[@]} -eq 0 ]] && selected=("${ORDER[@]}")

require_hub_image

# Every tag must exist locally before pushing anything, so a release is not left half pushed
missing=()
for variant in "${selected[@]}"; do
    while read -r name; do
        docker image inspect "$name" >/dev/null 2>&1 || missing+=("$name")
    done < <(image_tags "$variant")
done
if [[ ${#missing[@]} -gt 0 ]]; then
    echo "Not built locally (run: IMAGE=$IMAGE deployments/build.sh ${selected[*]}):" >&2
    printf '  %s\n' "${missing[@]}" >&2
    exit 1
fi

for variant in "${selected[@]}"; do
    echo "==> $variant"
    while read -r name; do
        docker push "$name"
    done < <(image_tags "$variant")
done

echo "Pushed: ${selected[*]} ($IMAGE, version $VERSION)"
echo "https://hub.docker.com/r/$IMAGE/tags"
