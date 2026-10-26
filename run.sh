#!/usr/bin/env bash
# Tank-G Control Center. Sin argumentos abre la interfaz gráfica; con argumentos, la CLI.
set -e
cd "$(dirname "$(readlink -f "$0")")"
if [ ! -x .venv/bin/python ]; then
    python3 -m venv .venv
    .venv/bin/pip install -q -r requirements.txt
fi
# Qt >= 6.5 needs libxcb-cursor0 for X11; on a Wayland session use the native backend first.
if [ -z "$WAYLAND_DISPLAY" ]; then
    sock=$(ls "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"/wayland-[0-9] 2>/dev/null | head -1)
    [ -n "$sock" ] && export WAYLAND_DISPLAY=$(basename "$sock")
fi
if ! ldconfig -p | grep -q libxcb-cursor.so.0; then
    if [ -n "$WAYLAND_DISPLAY" ]; then
        export QT_QPA_PLATFORM=wayland
    else
        echo "Falta libxcb-cursor0: sudo apt install libxcb-cursor0" >&2
        exit 1
    fi
elif [ -n "$WAYLAND_DISPLAY" ] && [ -z "$QT_QPA_PLATFORM" ]; then
    export QT_QPA_PLATFORM="wayland;xcb"
fi
[ -n "$TANKG_DEBUG" ] && echo "WAYLAND_DISPLAY=$WAYLAND_DISPLAY QT_QPA_PLATFORM=$QT_QPA_PLATFORM" >&2
exec .venv/bin/python -m tankg "$@"
