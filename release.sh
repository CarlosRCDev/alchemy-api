#!/usr/bin/env bash
# Release with the pyproject version: creates the tag v<version> and pushes it.
# GitHub Actions (.github/workflows/publish.yml) then runs the tests, builds and publishes
# to TestPyPI and PyPI. Nothing is published from this machine and no tokens are needed.
#
#   ./release.sh
#   SKIP_TESTS=1 ./release.sh     # without running the tests locally first
#
# Before: bump "version" in pyproject.toml, run "uv lock", commit and push to main.
set -euo pipefail

cd "$(dirname "$0")"

BRANCH="main"
VERSION="$(uv version --short)"
TAG="v$VERSION"
echo "Release $TAG"

# Checks before touching anything
uv lock --check || { echo "uv.lock out of date, run: uv lock" >&2; exit 1; }
[ -z "$(git status --porcelain)" ] || { echo "Working tree not clean, commit first" >&2; exit 1; }
[ "$(git branch --show-current)" = "$BRANCH" ] || { echo "Not on $BRANCH" >&2; exit 1; }
git fetch -q origin "$BRANCH" --tags
[ "$(git rev-parse HEAD)" = "$(git rev-parse "origin/$BRANCH")" ] \
    || { echo "HEAD is not origin/$BRANCH: push (or pull) first" >&2; exit 1; }
git rev-parse -q --verify "refs/tags/$TAG" >/dev/null && { echo "Tag $TAG already exists, bump the version in pyproject.toml" >&2; exit 1; }
git ls-remote --exit-code --tags origin "refs/tags/$TAG" >/dev/null && { echo "Tag $TAG already in origin" >&2; exit 1; }
status="$(curl -s -o /dev/null -w '%{http_code}' "https://pypi.org/pypi/sqlalchemy-rest-api/$VERSION/json" || true)"
[ "$status" != 200 ] || { echo "Version $VERSION already on PyPI, bump the version in pyproject.toml" >&2; exit 1; }

if [ -z "${SKIP_TESTS:-}" ]; then
    uv run pytest -q
fi

# Local tag, removed again if the push fails so the version can be retried
git tag -a "$TAG" -m "Release $VERSION"
trap 'echo "Failed: removing local tag $TAG" >&2; git tag -d "$TAG" >/dev/null' ERR
git push origin "$TAG"
trap - ERR

echo "Pushed $TAG: GitHub Actions tests, builds and publishes it"
echo "https://github.com/CarlosRCDev/alchemy-api/actions/workflows/publish.yml"
