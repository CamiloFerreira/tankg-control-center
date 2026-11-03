#!/usr/bin/env bash
# Packs the PyInstaller executable into a Debian package (Debian 12+, Ubuntu 22.04+, Mint, Pop!_OS…).
#   packaging/build_deb.sh [EXECUTABLE] [OUTPUT.deb]      (defaults: dist/TankG, dist/TankG-linux-amd64.deb)
# Installs /opt/tankg/TankG, the commands `tankg` and `TankG`, the menu entry and the icon.
# Version from tankg/version.py (or TANKG_VERSION). Needs only dpkg-deb.
set -euo pipefail
ROOT=$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)
BIN=$(readlink -f "${1:-$ROOT/dist/TankG}")
OUT=${2:-$ROOT/dist/TankG-linux-amd64.deb}
VERSION=${TANKG_VERSION:-$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$ROOT/tankg/version.py")}
[ -f "$BIN" ] || { echo "Falta el ejecutable $BIN: ejecuta primero  .venv/bin/python packaging/build.py" >&2; exit 1; }

umask 022
PKG=$(mktemp -d)
chmod 755 "$PKG"
trap 'rm -rf "$PKG"' EXIT
install -Dm755 "$BIN" "$PKG/opt/tankg/TankG"
mkdir -p "$PKG/usr/bin"
ln -s /opt/tankg/TankG "$PKG/usr/bin/tankg"
ln -s /opt/tankg/TankG "$PKG/usr/bin/TankG"
install -Dm644 "$ROOT/packaging/icon.png" "$PKG/usr/share/icons/hicolor/256x256/apps/tankg.png"
install -Dm644 "$ROOT/packaging/icon.svg" "$PKG/usr/share/icons/hicolor/scalable/apps/tankg.svg"
install -Dm644 /dev/stdin "$PKG/usr/share/applications/tankg.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=Tank-G Control Center
Comment=Gestor de presets para M-VAVE Tank-G
Exec=/opt/tankg/TankG
Icon=tankg
Terminal=false
Categories=AudioVideo;Audio;Music;
Keywords=guitar;pedal;midi;preset;m-vave;
StartupWMClass=TankG
DESKTOP
install -Dm644 /dev/stdin "$PKG/usr/share/doc/tankg-control-center/copyright" <<'COPY'
Tank-G Control Center — https://camiloferreira.github.io/tankg-control-center/
Copyright: Camilo Ferreira
COPY

SIZE=$(du -sk "$PKG" | cut -f1)
mkdir -p "$PKG/DEBIAN"
cat > "$PKG/DEBIAN/control" <<CONTROL
Package: tankg-control-center
Version: $VERSION
Section: sound
Priority: optional
Architecture: amd64
Installed-Size: $SIZE
Depends: libc6 (>= 2.35), libegl1, libgl1, libxkbcommon0, libfontconfig1
Recommends: bluez
Maintainer: Camilo Ferreira <camiloferrei9@gmail.com>
Homepage: https://camiloferreira.github.io/tankg-control-center/
Description: Gestor de presets para la pedalera M-VAVE Tank-G
 Lee, edita, respalda y escribe los 36 presets de la Tank-G por USB-MIDI o
 Bluetooth (Tank-G v2): setlists, biblioteca de bandas, IA, packs de AMP y
 sincronización con Google Drive. También funciona como línea de comandos
 (tankg list, tankg backup…).
CONTROL
cat > "$PKG/DEBIAN/postinst" <<'POST'
#!/bin/sh
set -e
command -v update-desktop-database >/dev/null && update-desktop-database -q /usr/share/applications || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q /usr/share/icons/hicolor || true
POST
cp "$PKG/DEBIAN/postinst" "$PKG/DEBIAN/postrm"
chmod 755 "$PKG/DEBIAN/postinst" "$PKG/DEBIAN/postrm"

mkdir -p "$(dirname "$OUT")"
dpkg-deb --root-owner-group -Zxz --build "$PKG" "$OUT" >/dev/null
echo "$OUT (tankg-control-center $VERSION)"
