"""Builds band packs (.tgpack): a bank of 4 presets per band with the AMP models (.am4data) of the
amp that band used, taken from the public M-VAVE community catalog (community.m-vave.com, the
"Community" tab of M-EFCS; no login needed). The models are third-party captures: every pack names
the author of each one ("credit" of its amps, ignored by the apps) and packs/CREDITS.md lists them.
The packs in packs/ (shipped with every app, BAND_PACKS in the APK) hold only a reference to each
model ({"community": {"article", "file"}}): the apps download it from its original publication when
the pack is imported, so they never redistribute third-party captures. --completo embeds the models
instead (offline packs for the user's own devices only; not for publishing).

    python3 tools/band_packs.py packs
    python3 tools/band_packs.py --completo ~/TankG-packs

Each model goes by default to one of the last TYPE slots (9, 8, 7), which the import window lets
the user change; presets that don't use a model use a factory AMP. Values are approximations by
ear, like tankg/artists.py; the GAIN of a captured model drives its input (the capture already has
the amp's own gain), so it stays near the middle.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tankg import am4, pack  # noqa: E402
from tankg.artists import AC30, CLOUD, CYAN, ENGL, JC, JCL, JVM, MESA, NOCAB, ORANGE, PINK, RED, ROOM, \
    ROOM_BIG, V30, WANGS, YELLOW, StylePreset  # noqa: E402
from tankg.model import Bank  # noqa: E402

API = "https://community.m-vave.com/bbs/api/"
UA = {"User-Agent": "Mozilla/5.0"}
M1, M2, M3 = 8, 7, 6          # default TYPE slots of the pack's models (AMP 9, 8, 7)


def download(article: int, file_name: str) -> bytes:
    url = API + "download?" + urllib.parse.urlencode({"articleId": article, "file": file_name})
    data = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read()
    am4.check(data)
    return data


# How to find each community entry again (its id is only reachable through a search).
SEARCH = {7414: "Randall RG100ES", 10062: "dimebag", 11546: "Master Of Puppets", 5880: "Mesa Boogie Dual Rectifier AM4Data",
          10830: "Silver Jubilee", 6392: "Plexi Super Lead", 8322: "Brown Sound", 11431: "JCM 800 2203", 7789: "EVH 5150 III",
          11401: "Peavey 5150", 9827: "Fender Twin Reverb", 7073: "Bassman", 11483: "1964 VOX", 7835: "Hiwatt",
          6609: "Soldano SLO-100"}


def entry(article: int) -> dict:
    req = urllib.request.Request(API + "getlist", data=json.dumps(
        {"search": SEARCH[article], "select": [], "sort": 1, "currentPage": 1, "pageSize": 50}).encode(),
        headers={"Content-Type": "application/json", **UA})
    for r in json.load(urllib.request.urlopen(req, timeout=30))["data"]["records"]:
        if r["id"] == article:
            return r
    raise SystemExit(f"community entry {article} not found")


def credit(article: int, file_name: str) -> dict:
    r = entry(article)
    original = sorted(set(re.findall(r"https?://(?:www\.)?tone3000\.com/[^\s)\]>,]+", r.get("content") or "")))
    return {"author": r["createUserName"], "title": r["title"], "file": file_name.split("_", 1)[-1],
            "source": f"community.m-vave.com · publicación #{article}", "original": original}


def P(name, amp, gain, eq, vol, gate, cab, role, mod=None, dly=None, rvb=None, desc=""):
    color = {"Limpio": CYAN, "Crunch": YELLOW, "Rítmica": RED, "Variante": ORANGE, "Solo": PINK}[role]
    return StylePreset(name, desc, amp, gain, eq, vol, gate, cab, mod, dly, rvb, color, role)


# (bank title, [(slot, model name, article id, file name)], 4 presets)
PACKS = [
    ("Pantera", [(M1, "Randall RG100ES '87", 7414, "b63088e9-7a49-4d4c-9973-1e616ea72180_randall.am4Data"),
                 (M2, "Randall Dimebag Walk", 10062, "e4eed9e6-da7b-4b48-85e8-c5456895d201_randall.am4Data")], [
        P("Cemetery Gates", JC, 18, (70, 58, 60), 88, 4, AC30, "Limpio", mod=("chorus", 35, 30), dly=("analog", 25, 50), rvb=ROOM_BIG),
        P("Cowboys from Hell", M1, 64, (74, 46, 78), 92, 46, MESA, "Rítmica", rvb=ROOM),
        P("Walk", M2, 62, (70, 50, 74), 92, 44, MESA, "Variante"),
        P("Solo Dimebag", M1, 74, (76, 66, 70), 100, 30, MESA, "Solo", dly=("tape", 30, 62), rvb=ROOM_BIG),
    ]),
    ("Metallica", [(M1, "Master of Puppets", 11546, "9583ef49-2e63-4da8-ab2a-b31e9ca6c3e5.am4Data"),
                   (M2, "Mesa Dual Rect Modern", 5880, "67cf4cfb-cb72-4dd2-93f7-68fe51620a5f_Dual Rect - Ch 2 Modern.am4Data")], [
        P("Fade to Black", JC, 20, (70, 60, 58), 88, 6, MESA, "Limpio", mod=("chorus", 35, 30), dly=("analog", 25, 55), rvb=("spring", 40, 30)),
        P("Master of Puppets", M1, 64, (72, 44, 76), 92, 42, MESA, "Rítmica", rvb=ROOM),
        P("Enter Sandman", M2, 62, (70, 50, 76), 92, 42, MESA, "Variante", rvb=ROOM),
        P("Solo Kirk", M1, 72, (74, 68, 66), 100, 26, MESA, "Solo", dly=("tape", 30, 60), rvb=ROOM_BIG),
    ]),
    ("Guns N' Roses", [(M1, "Silver Jubilee (Slash)", 10830, "d1792e33-ba2e-402c-bcd5-60034e5d412b_Silver_Jubilee_1987_Slash_Settings_CAB.am4Data"),
                       (M2, "Silver Jubilee Boost", 10830, "9d6bd719-480c-422b-9b66-1d674cfd9388_Silver_Jubilee_1987_Tweaked_Settings_CAB_BOOST_A2.am4Data")], [
        P("Patience", JCL, 22, (68, 62, 60), 88, 6, JVM, "Limpio", rvb=("spring", 35, 28)),
        P("Welcome to the Jungle", M1, 60, (68, 66, 62), 92, 18, NOCAB, "Rítmica", rvb=ROOM),
        P("Paradise City", M1, 66, (70, 64, 64), 92, 20, NOCAB, "Variante", rvb=ROOM),
        P("Solo Sweet Child", M2, 66, (70, 74, 60), 100, 16, NOCAB, "Solo", dly=("tape", 30, 62), rvb=ROOM_BIG),
    ]),
    ("AC/DC y Zeppelin", [(M1, "Plexi 1959 Vol 6", 6392, "8a2de1c2-7077-4857-a9c8-f23577ba4da0_Marshall Plexi Super Lead 1959(Input-I,Volume-6).am4Data"),
                          (M2, "Plexi 1959 Jumper Vol 8", 6392, "f648a2af-0c42-41cf-9f53-8365fae1fef8_Marshall Plexi Super Lead 1959(Input-I,Lo1+HI2,Volume-8).am4Data")], [
        P("Back in Black", M1, 60, (72, 68, 60), 92, 10, JVM, "Crunch", rvb=ROOM),
        P("Highway to Hell", M2, 58, (72, 66, 62), 92, 12, JVM, "Rítmica", rvb=ROOM),
        P("Whole Lotta Love", M2, 64, (70, 64, 64), 92, 12, JVM, "Variante", rvb=("spring", 30, 22)),
        P("Solo Angus / Page", M2, 70, (74, 74, 58), 100, 10, JVM, "Solo", dly=("tape", 25, 58), rvb=ROOM_BIG),
    ]),
    ("Van Halen", [(M1, "Brown Sound Natural", 8322, "b9f25563-c998-4e81-bec8-857b03b5e2b1_Unchained_Natural.am4Data"),
                   (M2, "Brown Sound Compressed", 8322, "c973e982-6bdf-4db3-94fa-aeee32a97e81_unchained_compressed.am4Data")], [
        P("Jamie's Cryin'", M1, 50, (70, 64, 60), 90, 8, JVM, "Crunch", rvb=ROOM),
        P("Unchained", M1, 64, (72, 62, 64), 92, 14, JVM, "Rítmica", mod=("phaser", 30, 20), rvb=ROOM),
        P("Panama", M2, 62, (72, 64, 62), 92, 14, JVM, "Variante", rvb=ROOM),
        P("Eruption", M2, 70, (74, 70, 60), 100, 12, JVM, "Solo", dly=("analog", 30, 58), rvb=ROOM_BIG),
    ]),
    ("Iron Maiden y Priest", [(M1, "JCM800 2203 Crunch", 11431, "c90b77bd-9753-4b0e-ab57-f9bb75693e2b_JCM800_2203__Crunch.am4data"),
                              (M2, "JCM800 2203 TS Boost", 11431, "c9ce50a5-de23-4c26-b76f-f8e4758169e9_JCM800_2203__Hi_Gain__TS_boost_.am4data")], [
        P("Remember Tomorrow", JC, 20, (68, 60, 58), 88, 6, JVM, "Limpio", mod=("chorus", 30, 28), rvb=("spring", 35, 26)),
        P("The Trooper", M2, 62, (70, 66, 66), 92, 24, JVM, "Rítmica", rvb=ROOM),
        P("Breaking the Law", M1, 66, (70, 64, 64), 92, 18, JVM, "Variante", rvb=ROOM),
        P("Solo Maiden", M2, 70, (72, 74, 60), 100, 20, JVM, "Solo", dly=("tape", 30, 60), rvb=ROOM_BIG),
    ]),
    ("Metal moderno 5150", [(M1, "EVH 5150 III", 7789, "270f0f00-b237-4081-9bfb-19e5c3f242d2_EVH 5150 III.am4Data"),
                            (M2, "Peavey 5150 (full rig)", 11401, "feac9466-3c40-4cb8-8fb0-a434287a0671_Peavey_5150_-_High_Gain_-_Full_Rig.am4Data")], [
        P("Limpio moderno", JC, 16, (72, 56, 56), 88, 6, ENGL, "Limpio", mod=("chorus", 25, 24), dly=("dual", 30, 60), rvb=CLOUD),
        P("5150 III Rítmica", M1, 62, (70, 50, 70), 92, 48, ENGL, "Rítmica"),
        P("5150 Chug", M2, 62, (68, 48, 72), 92, 50, NOCAB, "Variante"),
        P("Solo 5150", M1, 70, (72, 68, 62), 100, 30, V30, "Solo", dly=("tape", 30, 60), rvb=ROOM_BIG),
    ]),
    ("Blues y SRV", [(M1, "Fender Twin Ch2 Vib", 9827, "9743241d-91f3-4b3c-8c9f-883ad93185ab_01 Fender Ch2 Vib.am4Data"),
                     (M2, "Twin + TS808", 9827, "8ed2a475-c32f-40fd-a9d3-aa14e72a5698_05 Fender Twin Reverb TS808 g-11 di half.am4Data"),
                     (M3, "Fender Bassman '58 Clean", 7073, "a2b86bc1-cd82-44fc-8bda-848e333c836d_Fender Bassman '58 5F6A (Tweed) v4 [Clean] [Amp Only].am4Data")], [
        P("Twin limpio", M1, 56, (68, 62, 60), 90, 4, WANGS, "Limpio", rvb=("spring", 45, 34)),
        P("Texas Flood", M2, 60, (70, 72, 62), 92, 8, WANGS, "Rítmica", rvb=("spring", 35, 26)),
        P("Bassman tweed", M3, 58, (68, 66, 60), 90, 6, WANGS, "Variante", rvb=ROOM_BIG),
        P("Solo blues", M2, 66, (70, 76, 58), 100, 8, WANGS, "Solo", dly=("analog", 22, 55), rvb=("spring", 35, 26)),
    ]),
    ("Queen, U2 y Britpop", [(M1, "Vox AC30 1964 Top Boost", 11483, "95eae9a5-3927-4054-ad81-d6300db7849e.am4Data")], [
        P("Edge limpio", M1, 48, (74, 60, 56), 90, 6, AC30, "Limpio", dly=("dual", 70, 46), rvb=CLOUD),
        P("Britpop", M1, 60, (72, 64, 60), 92, 10, AC30, "Rítmica", rvb=ROOM),
        P("Brian May", M1, 66, (70, 70, 58), 92, 10, AC30, "Variante", dly=("tape", 30, 58), rvb=ROOM_BIG),
        P("Solo May", M1, 70, (70, 76, 56), 100, 10, AC30, "Solo", dly=("dual", 40, 62), rvb=ROOM_BIG),
    ]),
    ("Pink Floyd", [(M1, "Hiwatt DR103 + Klon", 7835, "701f1a67-99ad-4a73-8943-004b986f0b42_Hiwatt DR 103 TS808_Archer Klon high gain.am4Data")], [
        P("Breathe", JC, 20, (68, 60, 58), 88, 4, AC30, "Limpio", mod=("chorus", 20, 20), dly=("tape", 30, 70), rvb=CLOUD),
        P("Money", M1, 52, (68, 64, 62), 92, 10, JVM, "Rítmica", rvb=ROOM),
        P("Another Brick", JCL, 30, (72, 60, 58), 90, 6, AC30, "Variante", dly=("analog", 30, 40), rvb=ROOM),
        P("Comfortably Numb", M1, 70, (72, 76, 64), 100, 14, JVM, "Solo", dly=("tape", 40, 75), rvb=CLOUD),
    ]),
    ("Ozzy y Zakk Wylde", [(M1, "Soldano SLO-100 Crunch", 6609, "24af59d8-bbfb-4c25-b1fc-5e5376ef0599_NDSP Soldano SLO-100 X Crunch.am4Data"),
                           (M2, "Soldano SLO-100 Lead", 6609, "c772af38-adf8-4dab-a66a-2d075b65f558_NDSP Soldano SLO-100 X SLO Lead.am4Data")], [
        P("Mama I'm Coming Home", JCL, 24, (68, 62, 60), 88, 6, JVM, "Limpio", mod=("chorus", 25, 26), rvb=("spring", 35, 26)),
        P("Crazy Train", M1, 62, (70, 64, 66), 92, 20, JVM, "Rítmica", rvb=ROOM),
        P("No More Tears", M2, 60, (70, 58, 70), 92, 34, ENGL, "Variante", rvb=ROOM),
        P("Solo Zakk", M2, 70, (72, 72, 62), 100, 28, ENGL, "Solo", dly=("tape", 28, 58), rvb=ROOM_BIG),
    ]),
]


def main(out: Path, full: bool = False) -> None:
    out.mkdir(parents=True, exist_ok=True)
    empty = Bank.from_bytes(b"\xa5\x5a" + bytes(21 * 36))
    rows = []
    for n, (title, models, presets) in enumerate(PACKS):
        data, names, credits, refs = {}, {}, {}, {}
        for slot, name, article, file_name in models:
            data[slot] = download(article, file_name)   # checks that it is a valid AM4 model
            names[str(slot + 1)] = name
            credits[slot + 1] = credit(article, file_name)
            refs[slot + 1] = {"article": article, "file": file_name}
        bank = empty.copy()
        for i, p in enumerate(presets):
            bank.presets[i] = p.build()
        doc, missing = pack.make(bank, [0, 1, 2, 3], {i: p.name for i, p in enumerate(presets)}, {"1": title}, names, data, title)
        assert not missing and len(doc["amps"]) == len(models)
        for amp in doc["amps"]:
            amp["credit"] = credits[amp["slot"]]
            if not full:
                del amp["data"]
                amp["community"] = refs[amp["slot"]]
        doc["source"] = ("Modelos de AMP: capturas de sus autores publicadas en la comunidad de M-VAVE "
                         "(community.m-vave.com); ver «credit» de cada uno. Solo para uso personal.")
        path = pack.save(doc, out / f"{n + 1:02d} {title.replace('/', '-')}{pack.EXTENSION}")
        rows.append((path.name, doc["amps"]))
        print(f"{path.name}: {', '.join(m[1] for m in models)}")
    lines = ["# Créditos de los modelos de AMP", "",
             "Los modelos (.am4data) de estos packs **no son de este proyecto**: son capturas de sus autores, "
             "publicadas en la comunidad de M-VAVE (community.m-vave.com, pestaña «Community» de M-EFCS), muchas "
             "convertidas de capturas NAM de TONE3000. No se redistribuyen "
             "(los packs de las apps solo llevan una referencia y cada app descarga el modelo de su publicación original "
             "al importarlo). Generado por `tools/band_packs.py`.", ""]
    for name, amps in rows:
        lines.append(f"## {name}")
        for a in amps:
            c = a["credit"]
            orig = f" · original: {', '.join(c['original'])}" if c["original"] else ""
            lines.append(f"- AMP {a['slot']} «{a['name']}»: «{c['title']}» de **{c['author']}** ({c['source']}, "
                         f"archivo {c['file']}){orig}")
        lines.append("")
    (out / "CREDITS.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--completo"]
    main(Path(args[0]), full="--completo" in sys.argv)
