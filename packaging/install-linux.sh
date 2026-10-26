#!/usr/bin/env bash
# Installs dist/TankG into ~/.local/bin and adds "Tank-G Control Center" to the applications menu.
set -e
cd "$(dirname "$(readlink -f "$0")")/.."
[ -x dist/TankG ] || { echo "Falta dist/TankG: ejecuta primero  .venv/bin/python packaging/build.py" >&2; exit 1; }
install -Dm755 dist/TankG "$HOME/.local/bin/TankG"
install -Dm644 packaging/icon.png "$HOME/.local/share/icons/hicolor/256x256/apps/tankg.png"
install -Dm644 /dev/stdin "$HOME/.local/share/applications/tankg.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Tank-G Control Center
Comment=Gestor de presets para M-VAVE Tank-G
Exec=$HOME/.local/bin/TankG
Icon=tankg
Terminal=false
Categories=AudioVideo;Audio;Music;
DESKTOP
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
echo "Instalado: $HOME/.local/bin/TankG (también en el menú de aplicaciones como «Tank-G Control Center»)"
