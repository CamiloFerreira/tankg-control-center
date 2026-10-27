#!/usr/bin/env bash
# Copies a release of this (private) repo to the public releases repo, where the apps look for
# updates. Adds the signed APK from dist/ when the release has none (CI without the key secrets).
#   tools/publish_release.sh v1.5.0
set -euo pipefail
TAG=${1:?usage: tools/publish_release.sh vX.Y.Z}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
REPO=$(sed -n 's/^RELEASES_REPO = "\(.*\)"/\1/p' "$ROOT/tankg/version.py")
WORK=$(mktemp -d)
trap 'rm -r "$WORK"' EXIT
gh release download "$TAG" -D "$WORK" --repo "$(gh repo view --json nameWithOwner -q .nameWithOwner)"
gh release view "$TAG" --json body -q .body > "$WORK/notes.md"
if [ ! -f "$WORK/TankG-android.apk" ]; then
  [ -f "$ROOT/dist/TankG.apk" ] || { echo "Falta la APK: android/build.sh"; exit 1; }
  grep -q "versionName='${TAG#v}'" <("${ANDROID_HOME:-$HOME/Android/Sdk}/build-tools/35.0.0/aapt2" dump badging "$ROOT/dist/TankG.apk") \
    || { echo "dist/TankG.apk no es la versión ${TAG#v}: android/build.sh"; exit 1; }
  cp "$ROOT/dist/TankG.apk" "$WORK/TankG-android.apk"
  (cd "$WORK" && sha256sum TankG-android.apk >> SHA256SUMS)
  gh release upload "$TAG" "$WORK/TankG-android.apk" "$WORK/SHA256SUMS" --clobber
fi
(cd "$WORK" && sha256sum -c SHA256SUMS)
gh release create "$TAG" "$WORK"/TankG-* "$WORK/SHA256SUMS" "$WORK"/*.cer --repo "$REPO" \
  --title "Tank-G Control Center $TAG" --notes-file "$WORK/notes.md" 2>/dev/null \
  || gh release create "$TAG" "$WORK"/TankG-* "$WORK/SHA256SUMS" --repo "$REPO" \
       --title "Tank-G Control Center $TAG" --notes-file "$WORK/notes.md"
echo "https://github.com/$REPO/releases/tag/$TAG"
