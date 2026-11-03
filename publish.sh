#!/usr/bin/env bash
# Release with the pyproject version
#
#   ./publish.sh tag        # tag + push: GitHub Actions builds and publishes (.github/workflows/publish.yml)
#   ./publish.sh            # manual: tag -> uv build -> publish to TestPyPI -> push the tag
#   ./publish.sh pypi       # manual, to PyPI
#   SKIP_TESTS=1 ./publish.sh ...
#
# Manual modes need tokens, never written here. Set them in the environment or in .publish.env (git ignored):
#   UV_PUBLISH_TOKEN_TESTPYPI=pypi-...
#   UV_PUBLISH_TOKEN_PYPI=pypi-...
set -euo pipefail

cd "$(dirname "$0")"
[ -f .publish.env ] && . ./.publish.env

TARGET="${1:-testpypi}"
case "$TARGET" in
    tag)
        ;;
    testpypi)
        PUBLISH_URL="https://test.pypi.org/legacy/"
        TOKEN="${UV_PUBLISH_TOKEN_TESTPYPI:-}"
        ;;
    pypi)
        PUBLISH_URL="https://upload.pypi.org/legacy/"
        TOKEN="${UV_PUBLISH_TOKEN_PYPI:-}"
        ;;
    *)
        echo "Usage: $0 [tag|testpypi|pypi]" >&2
        exit 2
        ;;
esac
[ "$TARGET" = tag ] || [ -n "$TOKEN" ] || { echo "Token for $TARGET not set (UV_PUBLISH_TOKEN_${TARGET^^})" >&2; exit 1; }

VERSION="$(uv version --short)"
TAG="v$VERSION"
echo "Release $TAG -> $TARGET"

# Checks before touching anything
uv lock --check || { echo "uv.lock out of date, run: uv lock" >&2; exit 1; }
[ -z "$(git status --porcelain)" ] || { echo "Working tree not clean, commit first" >&2; exit 1; }
git rev-parse -q --verify "refs/tags/$TAG" >/dev/null && { echo "Tag $TAG already exists, bump the version in pyproject.toml" >&2; exit 1; }
git ls-remote --exit-code --tags origin "refs/tags/$TAG" >/dev/null && { echo "Tag $TAG already in origin" >&2; exit 1; }

if [ -z "${SKIP_TESTS:-}" ]; then
    uv run pytest -q
fi

# 1. Local tag; removed again if push, build or publish fail, so the version can be retried
git tag -a "$TAG" -m "Release $VERSION"
trap 'echo "Failed: removing local tag $TAG" >&2; git tag -d "$TAG" >/dev/null' ERR

if [ "$TARGET" = tag ]; then
    git push origin "$TAG"
    echo "Pushed $TAG: GitHub Actions builds and publishes it"
    exit 0
fi

# 2. Build from a clean dist/
rm -rf dist
uv build

# 3. Publish
uv publish --publish-url "$PUBLISH_URL" --token "$TOKEN"
trap - ERR

# 4. Push the tag only once the package is published
git push origin "$TAG"
echo "Published $TAG to $TARGET"
