# Shared by build.sh and push.sh (sourced, not run): image variants, settings and tags.

# variant -> EXTRAS build arg
declare -A VARIANTS=(
    [all]="async,postgres,mariadb,mysql,mssql,oracle,jwt,mcp"
    [sqlite]="async,jwt,mcp"
    [postgres]="async,postgres,jwt,mcp"
    # [mariadb]="async,mariadb"
    [mysql]="async,mysql,jwt,mcp"
    [mssql]="async,mssql,jwt,mcp"
    [oracle]="async,oracle,jwt,mcp"
)
# ORDER=(all sqlite postgres mariadb mysql mssql oracle)
ORDER=(all sqlite postgres mysql mssql oracle)

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${IMAGE:-sqlalchemy-rest-api}"
VERSION="${VERSION:-$(sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT/pyproject.toml" | head -1)}"
LATEST="${LATEST:-true}"

if [[ -z "$VERSION" ]]; then
    echo "Version not found in pyproject.toml, set VERSION" >&2
    exit 1
fi

usage() {
    # Header comment of the running script, until the first non comment line
    awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"
    echo "Variants: ${ORDER[*]}"
}

# check_variant <name>: exits if the variant does not exist
check_variant() {
    if [[ -z "${VARIANTS[$1]+x}" ]]; then
        echo "Unknown variant: $1 (valid: ${ORDER[*]})" >&2
        exit 1
    fi
}

# require_hub_image: Docker Hub needs the user in the image name
require_hub_image() {
    if [[ "$IMAGE" != */* ]]; then
        echo "To push, IMAGE must include the Docker Hub user: IMAGE=user/sqlalchemy-rest-api" >&2
        exit 1
    fi
}

# image_tags <variant>: one full image tag per line.
# <variant> and <version>-<variant>; "all" also <version> and latest (unless LATEST=false)
image_tags() {
    echo "$IMAGE:$1"
    echo "$IMAGE:$VERSION-$1"
    if [[ "$1" == all ]]; then
        echo "$IMAGE:$VERSION"
        if [[ "$LATEST" != false ]]; then
            echo "$IMAGE:latest"
        fi
    fi
}
