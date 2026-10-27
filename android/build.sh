#!/usr/bin/env bash
# Builds the Android APK with the SDK build tools only (aapt2, javac, d8, apksigner): no Gradle.
#   android/build.sh            release APK, signed with the release key  -> dist/TankG.apk
#   android/build.sh debug      debuggable APK (chrome://inspect works)    -> dist/TankG-debug.apk
# Needs ANDROID_HOME (default ~/Android/Sdk) with platforms;android-34 and build-tools;35.0.0.
# Release key: $TANKG_KEYSTORE (default ~/.local/share/tankg/android-release.jks), password in
# $TANKG_KEYSTORE_PASS or in the .pass file next to it; both are created on first use. Keep them:
# Android only installs updates signed with the same key.
set -euo pipefail
MODE=${1:-release}
SDK=${ANDROID_HOME:-$HOME/Android/Sdk}
BT=$SDK/build-tools/35.0.0   # d8 from 34.0.0 crashes on classes built by JDK 21
JAR=$SDK/platforms/android-34/android.jar
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(dirname "$HERE")
OUT=$HERE/build
rm -rf "$OUT" && mkdir -p "$OUT/classes" "$OUT/assets" "$ROOT/dist"

VERSION=${TANKG_VERSION:-$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$ROOT/tankg/version.py")}   # single source
IFS=. read -r MA MI PA <<<"$VERSION"
VCODE=$(( ${MA:-1} * 10000 + ${MI:-0} * 100 + ${PA:-0} ))

cp -r "$HERE/ui" "$OUT/assets/web"
rm -f "$OUT/assets/web/package.json"

DEBUG_FLAG=()
[ "$MODE" = debug ] && DEBUG_FLAG=(--debug-mode)
"$BT/aapt2" compile --dir "$HERE/res" -o "$OUT/res.zip"
"$BT/aapt2" link -o "$OUT/unsigned.apk" -I "$JAR" --manifest "$HERE/AndroidManifest.xml" \
  --min-sdk-version 23 --target-sdk-version 34 --version-code "$VCODE" --version-name "$VERSION" \
  -A "$OUT/assets" "${DEBUG_FLAG[@]}" "$OUT/res.zip"

javac -nowarn -XDstringConcat=inline --release 11 -cp "$JAR" -d "$OUT/classes" $(find "$HERE/src" -name '*.java')
D8_MODE=--release
[ "$MODE" = debug ] && D8_MODE=--debug
"$BT/d8" $D8_MODE --min-api 23 --lib "$JAR" --output "$OUT" $(find "$OUT/classes" -name '*.class')
(cd "$OUT" && zip -q unsigned.apk classes.dex)
"$BT/zipalign" -f -p 4 "$OUT/unsigned.apk" "$OUT/aligned.apk"

if [ "$MODE" = debug ]; then
  KS=$HOME/.android/debug.keystore PASS=android ALIAS=androiddebugkey
  [ -f "$KS" ] || { mkdir -p "$(dirname "$KS")"; keytool -genkeypair -keystore "$KS" -storepass android -keypass android \
    -alias androiddebugkey -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=Android Debug,O=Android,C=US" >/dev/null; }
  APK=$ROOT/dist/TankG-debug.apk
else
  KS=${TANKG_KEYSTORE:-$HOME/.local/share/tankg/android-release.jks} ALIAS=tankg
  PASSFILE=${KS%.jks}.pass
  if [ -n "${TANKG_KEYSTORE_PASS:-}" ]; then PASS=$TANKG_KEYSTORE_PASS
  elif [ -f "$PASSFILE" ]; then PASS=$(cat "$PASSFILE")
  else
    mkdir -p "$(dirname "$KS")"; umask 077
    PASS=$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 24); printf '%s' "$PASS" > "$PASSFILE"
  fi
  [ -f "$KS" ] || keytool -genkeypair -keystore "$KS" -storepass "$PASS" -keypass "$PASS" -alias "$ALIAS" \
    -keyalg RSA -keysize 3072 -validity 12000 -dname "CN=Tank-G Control" >/dev/null
  APK=$ROOT/dist/TankG.apk
fi
"$BT/apksigner" sign --ks "$KS" --ks-pass "pass:$PASS" --ks-key-alias "$ALIAS" --out "$APK" "$OUT/aligned.apk"
chmod 644 "$APK"   # the umask above only protects the key files
"$BT/apksigner" verify "$APK"
echo "$APK  (versión $VERSION, código $VCODE)"
