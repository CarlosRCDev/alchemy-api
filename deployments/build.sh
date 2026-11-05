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

# variant -> EXTRAS build arg
declare -A VARIANTS=(
    [all]="async,postgres,mariadb,mysql,mssql,oracle"
    [sqlite]="async"
    [postgres]="async,postgres"
    # [mariadb]="async,mariadb"
    [mysql]="async,mysql"
    [mssql]="async,mssql"
    [oracle]="async,oracle"
)
# ORDER=(all sqlite postgres mariadb mysql mssql oracle)
ORDER=(all sqlite postgres mysql mssql oracle)

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${IMAGE:-sqlalchemy-rest-api}"
VERSION="${VERSION:-$(sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT/pyproject.toml" | head -1)}"
PLATFORMS="${PLATFORMS:-}"
LATEST="${LATEST:-true}"
PUSH=false

usage() {
    # Header comment of this file, until the first non comment line
    awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "${BASH_SOURCE[0]}"
    echo "Variants: ${ORDER[*]}"
}

selected=()
for arg in "$@"; do
    case "$arg" in
        --push) PUSH=true ;;
        -h|--help) usage; exit 0 ;;
        -*) echo "Unknown option: $arg" >&2; usage >&2; exit 1 ;;
        *)
            if [[ -z "${VARIANTS[$arg]+x}" ]]; then
                echo "Unknown variant: $arg (valid: ${ORDER[*]})" >&2
                exit 1
            fi
            selected+=("$arg")
            ;;
    esac
done
[[ ${#selected[@]} -eq 0 ]] && selected=("${ORDER[@]}")

if [[ -z "$VERSION" ]]; then
    echo "Version not found in pyproject.toml, set VERSION" >&2
    exit 1
fi
if $PUSH && [[ "$IMAGE" != */* ]]; then
    echo "To push, IMAGE must include the Docker Hub user: IMAGE=user/sqlalchemy-rest-api" >&2
    exit 1
fi
if [[ -n "$PLATFORMS" ]] && ! $PUSH; then
    # A multi architecture image can not be loaded in the local docker, only pushed
    echo "PLATFORMS needs --push" >&2
    exit 1
fi

for variant in "${selected[@]}"; do
    tags=(-t "$IMAGE:$variant" -t "$IMAGE:$VERSION-$variant")
    if [[ "$variant" == all ]]; then
        tags+=(-t "$IMAGE:$VERSION")
        if [[ "$LATEST" != false ]]; then
            tags+=(-t "$IMAGE:latest")
        fi
    fi
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
            for ((i = 1; i < ${#tags[@]}; i += 2)); do
                docker push "${tags[$i]}"
            done
        fi
    fi
done

echo "Done: ${selected[*]} ($IMAGE, version $VERSION)"
