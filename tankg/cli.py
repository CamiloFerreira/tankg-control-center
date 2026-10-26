"""Command-line interface. Every command that writes to the pedal first saves an automatic
backup, writes only the slots that change, and verifies them by reading back."""
from __future__ import annotations

import argparse
import sys

from . import library
from .device import DeviceError, TankG, find_devices, list_midi_ports
from .model import AMP_MODELS, CAB_MODELS, FIELDS, Bank, parse_slot, slot_name


def print_bank(bank: Bank, other: Bank | None = None) -> None:
    print("Slot  AMP         CAB           Knobs (inferido)     Raw")
    for i, p in enumerate(bank.presets):
        mark = "*" if other is not None and other.presets[i] != p else " "
        knobs = " ".join(f"{k:3d}" for k in p.knobs)
        print(f"{slot_name(i)}{mark}   {p.amp_name:<11} {p.cab_name:<13} {knobs}  {p.to_bytes().hex()}")


def apply(dev: TankG, current: Bank, target: Bank, select: int | None = None) -> None:
    slots = target.diff_slots(current)
    if not slots:
        print("Sin cambios.")
        return
    path = library.backup(current, "auto")
    print(f"Backup: {path}")
    print("Escribiendo:", ", ".join(slot_name(s) for s in slots))
    dev.write_presets(target, slots)
    print("Verificado por relectura.")
    if select is not None:
        dev.select_preset(select)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tankg", description="M-VAVE Tank-G preset manager")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("info", help="detectar la pedalera")
    p = sub.add_parser("ports", help="listar puertos MIDI y elegir cuáles usar")
    p.add_argument("--in", dest="port_in", help="nombre exacto del puerto de entrada")
    p.add_argument("--out", dest="port_out", help="nombre exacto del puerto de salida")
    p.add_argument("--auto", action="store_true", help="volver a la detección automática")
    p = sub.add_parser("list", help="listar presets (de la pedalera o de un archivo)")
    p.add_argument("--file")
    p = sub.add_parser("backup", help="guardar el banco completo")
    p.add_argument("path", nargs="?")
    p = sub.add_parser("restore", help="enviar un banco completo (.tgbank) a la pedalera")
    p.add_argument("path")
    p = sub.add_parser("diff", help="comparar la pedalera con un archivo de banco")
    p.add_argument("path")
    p = sub.add_parser("export", help="guardar un preset en .tgpreset")
    p.add_argument("slot")
    p.add_argument("path")
    p = sub.add_parser("import", help="cargar un .tgpreset en un slot")
    p.add_argument("path")
    p.add_argument("slot")
    p = sub.add_parser("copy", help="copiar un preset a otro slot")
    p.add_argument("src")
    p.add_argument("dst")
    p = sub.add_parser("swap", help="intercambiar dos presets")
    p.add_argument("a")
    p.add_argument("b")
    p = sub.add_parser("reset", help="restaurar un slot al preset de fábrica")
    p.add_argument("slot")
    p = sub.add_parser("set", help="cambiar AMP/CAB de un preset")
    p.add_argument("slot")
    p.add_argument("--amp", type=int, help=", ".join(f"{i}={n}" for i, n in enumerate(AMP_MODELS)))
    p.add_argument("--cab", type=int, help=", ".join(f"{i}={n}" for i, n in enumerate(CAB_MODELS)))
    p.add_argument("--field", action="append", default=[], metavar="CLAVE=VALOR",
                   help="cualquier campo: " + ", ".join(f.key for f in FIELDS))
    p = sub.add_parser("select", help="activar un preset en la pedalera")
    p.add_argument("slot")
    a = ap.parse_args(argv)

    try:
        if a.cmd == "list" and a.file:
            print_bank(library.load_bank(a.file))
            return 0
        if a.cmd == "ports":
            settings = library.Settings()
            if a.auto:
                settings.set_midi_ports(None)
            elif a.port_in or a.port_out:
                if not (a.port_in and a.port_out):
                    raise ValueError("indica --in y --out")
                settings.set_midi_ports((a.port_in, a.port_out))
            ins, outs = list_midi_ports()
            print("Entradas:\n" + "\n".join(f"  {n}" for n in ins))
            print("Salidas:\n" + "\n".join(f"  {n}" for n in outs))
            sel = settings.midi_ports
            print("Selección:", f"entrada «{sel[0]}», salida «{sel[1]}»" if sel else "automática")
            return 0
        if a.cmd == "info":
            devs = find_devices()
            if not devs:
                print("No se encontró la Tank-G. Usa «ports» para ver los puertos MIDI y elegir uno.")
                return 1
            for d in devs:
                print(d.describe())
            dev = TankG.open(devs[0])
            dev.close()
            print("Banco Tank-G leído correctamente (36 presets).")
            return 0

        dev = TankG.open()
        try:
            current = dev.read_bank()
            target = current.copy()
            if a.cmd == "list":
                print_bank(current)
            elif a.cmd == "backup":
                path = library.save_bank(current, a.path) if a.path else library.backup(current, "manual")
                print(f"Guardado: {path}")
            elif a.cmd == "diff":
                other = library.load_bank(a.path)
                slots = current.diff_slots(other)
                print("Idénticos." if not slots else "Distintos: " + ", ".join(slot_name(s) for s in slots))
            elif a.cmd == "export":
                s = parse_slot(a.slot)
                print(f"Guardado: {library.save_preset(current.presets[s], a.path, s)}")
            elif a.cmd == "select":
                dev.select_preset(parse_slot(a.slot))
            else:
                select = None
                if a.cmd == "restore":
                    target = library.load_bank(a.path)
                elif a.cmd == "import":
                    select = parse_slot(a.slot)
                    target.presets[select] = library.load_preset(a.path)
                elif a.cmd == "copy":
                    select = parse_slot(a.dst)
                    target.presets[select] = current.presets[parse_slot(a.src)].copy()
                elif a.cmd == "swap":
                    x, y = parse_slot(a.a), parse_slot(a.b)
                    target.presets[x], target.presets[y] = current.presets[y].copy(), current.presets[x].copy()
                elif a.cmd == "reset":
                    factory = library.factory_bank()
                    if factory is None:
                        raise DeviceError("No hay banco de fábrica disponible (research/factory/tankG_am4_preset.bin).")
                    select = parse_slot(a.slot)
                    target.presets[select] = factory.presets[select].copy()
                elif a.cmd == "set":
                    select = parse_slot(a.slot)
                    if a.amp is not None:
                        target.presets[select].amp = a.amp
                    if a.cab is not None:
                        target.presets[select].cab = a.cab
                    for item in a.field:
                        key, _, value = item.partition("=")
                        if key not in {f.key for f in FIELDS}:
                            raise ValueError(f"campo desconocido: {key}")
                        target.presets[select].set(key, int(value, 0))
                apply(dev, current, target, select)
        finally:
            dev.close()
    except (DeviceError, ValueError, OSError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
