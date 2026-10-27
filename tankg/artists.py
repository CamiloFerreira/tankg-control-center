"""Ready-made presets inspired by well-known bands and styles, so there are plenty of sounds
without using the AI. One bank of four per band, always in the same order:

  A  Limpio   (Crunch when the band hardly ever plays clean)
  B  Rítmica  the band's main distorted sound
  C  variant  a second distorted sound: another song, era or a tighter riff tone
  D  Solo     more mids, volume and delay

Sounds not written out by hand are derived from the rhythm tone (_clean_of, _crunch_of,
_heavy_of, _solo_of). Values are approximations by ear of each artist's typical rig, written
as AI "designs" and turned into bytes by ai.apply_design, so they inherit the same field map
(only AMP and CAB verified; the rest and the three-zone limits are inferred, see
research/FINDINGS.md).
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from .ai import apply_design
from .model import AMP_MODELS, CAB_MODELS, Preset

# Short aliases for AMP_MODELS / CAB_MODELS indices, to keep the tables below readable.
JC, JCL, TS, RAT, HTS, DS, GV2, JHV, BB = range(9)
NOCAB, AC210, JVM, MESA, WANGS, AC30, YAMAHA, ENGL, V30 = range(9)

RED, ORANGE, YELLOW, CYAN, PINK = (255, 0, 0), (255, 110, 0), (255, 200, 0), (0, 200, 255), (255, 0, 140)
ROLE_COLORS = {"Limpio": CYAN, "Crunch": YELLOW, "Rítmica": RED, "Variante": ORANGE, "Solo": PINK}

# Recurring effect settings.
ROOM = ("room", 20, 14)
ROOM_BIG = ("room", 30, 20)
CLOUD = ("cloud", 45, 30)


@dataclass(frozen=True)
class StylePreset:
    name: str
    desc: str
    amp: int
    gain: int
    eq: tuple[int, int, int]               # treble, middle, bass (0-127)
    volume: int
    gate: int
    cab: int
    mod: tuple[str, int, int] | None = None   # (chorus|phaser|tremolo, amount 0-100, speed 0-127)
    dly: tuple[str, int, int] | None = None   # (analog|tape|dual, mix 0-100, time 0-127)
    rvb: tuple[str, int, int] | None = None   # (room|spring|cloud, decay 0-100, mix 0-127)
    color: tuple[int, int, int] = RED
    role: str = ""                            # Limpio, Crunch, Rítmica, Variante, Solo

    def design(self) -> dict:
        mod = self.mod or ("chorus", 0, 0)
        dly = self.dly or ("analog", 0, 0)
        rvb = self.rvb or ("room", 0, 0)
        return dict(amp_on=True, amp_type=self.amp, gain=self.gain, treble=self.eq[0], middle=self.eq[1],
                    bass=self.eq[2], volume=self.volume, gate=self.gate, cab=self.cab,
                    mod_on=self.mod is not None, mod_type=mod[0], mod_amount=mod[1], mod_speed=mod[2],
                    dly_on=self.dly is not None, dly_type=dly[0], dly_mix=dly[1], dly_time=dly[2],
                    rvb_on=self.rvb is not None, rvb_type=rvb[0], rvb_decay=rvb[1], rvb_mix=rvb[2],
                    led_color=list(self.color))

    def build(self, like: Preset | None = None) -> Preset:
        return apply_design(self.design(), like)

    def summary(self) -> str:
        parts = [f"{AMP_MODELS[self.amp]} · gain {self.gain}", CAB_MODELS[self.cab]]
        parts += [f"{fx[0]}" for fx in (self.mod, self.dly, self.rvb) if fx]
        return " · ".join(parts)


@dataclass(frozen=True)
class StyleBank:
    genre: str
    name: str
    presets: tuple[StylePreset, StylePreset, StylePreset, StylePreset]


def T(amp: int, gain: int, eq: tuple[int, int, int], gate: int, cab: int, vol: int = 92,
      mod=None, dly=None, rvb=None, desc: str = "") -> StylePreset:
    """A tone without name/role yet."""
    return StylePreset("", desc, amp, gain, eq, vol, gate, cab, mod, dly, rvb)


def _clean_of(r: StylePreset) -> StylePreset:
    amp = JCL if r.cab in (JVM, WANGS) else JC
    big = r.rvb is not None and r.rvb[0] == "cloud"
    return T(amp, 18, (72, 60, 56), 6, r.cab, 88, mod=("chorus", 30, 24), dly=("analog", 22, 55),
             rvb=("cloud", 50, 36) if big else ("room", 35, 26), desc="limpio con chorus y delay para intros y baladas")


def _crunch_of(r: StylePreset) -> StylePreset:
    amp = JHV if r.amp == DS else r.amp   # the MT-2 gets fizzy at low gain
    return replace(r, amp=amp, gain=max(45, r.gain * 2 // 3), gate=max(8, r.gate // 2), dly=None,
                   desc="menos ganancia para versos, acordes abiertos y partes suaves")


def _heavy_of(r: StylePreset) -> StylePreset:
    return replace(r, gain=min(124, r.gain + 8), eq=(min(95, r.eq[0] + 4), max(25, r.eq[1] - 8), r.eq[2]),
                   gate=min(55, r.gate + 6), desc="variante más apretada para riffs rápidos")


def _solo_of(r: StylePreset) -> StylePreset:
    amp = {GV2: JHV, BB: HTS, TS: HTS, JC: JCL}.get(r.amp, r.amp)
    rvb = r.rvb if r.rvb and r.rvb[0] == "cloud" else ("room", 30, 22)
    return replace(r, amp=amp, gain=min(124, r.gain + 8), eq=(r.eq[0], min(88, r.eq[1] + 14), max(55, r.eq[2] - 6)),
                   volume=min(100, r.volume + 8), gate=max(10, r.gate - 12), mod=None, dly=("tape", 28, 55),
                   rvb=rvb, desc="lead con más medios, volumen y delay de cinta")


_AUTO = object()


def band(genre: str, name: str, short: str, rhythm: StylePreset, alt: tuple[str, StylePreset] | None = None,
         clean=_AUTO, solo: StylePreset | None = None) -> StyleBank:
    """Bank A-D for one band. clean=None: the band hardly plays clean, slot A gets a crunch.
    Preset names are "<short> <role>"; the variant is named after its song."""
    a = (_crunch_of(rhythm), "Crunch") if clean is None else (_clean_of(rhythm) if clean is _AUTO else clean, "Limpio")
    c_name, c = alt if alt else (f"{short} Pesada", _heavy_of(rhythm))
    slots = [(f"{short} {a[1]}", a[0], a[1]), (f"{short} Rítmica", rhythm, "Rítmica"),
             (c_name, c, "Variante"), (f"{short} Solo", solo or _solo_of(rhythm), "Solo")]
    return StyleBank(genre, name, tuple(
        replace(t, name=n, role=role, color=ROLE_COLORS[role], desc=f"{name}: {t.desc}" if t.desc else name)
        for n, t, role in slots))


def style(genre: str, name: str, *items: tuple[str, str, StylePreset]) -> StyleBank:
    """Bank for a style rather than a band: (role, name, tone) x 4, in A-D order."""
    return StyleBank(genre, name, tuple(replace(t, name=n, role=role, color=ROLE_COLORS[role])
                                        for role, n, t in items))


BANKS: list[StyleBank] = [
    # básicos (puntos de partida genéricos) ----------------------------------------------------
    style("Básicos", "Guitarra eléctrica",
          ("Limpio", "Básico Limpio", T(JC, 15, (66, 63, 63), 10, AC210, 90, rvb=ROOM_BIG, desc="limpio neutro")),
          ("Crunch", "Básico Crunch", T(GV2, 45, (66, 68, 63), 15, JVM, rvb=("room", 20, 12),
                                        desc="crunch británico")),
          ("Rítmica", "Básico Distorsión", T(JHV, 70, (64, 64, 63), 30, JVM, rvb=("room", 15, 10),
                                             desc="distorsión de rock")),
          ("Solo", "Básico Solo", T(JHV, 78, (66, 74, 60), 24, V30, 98, dly=("analog", 22, 60), rvb=ROOM_BIG,
                                    desc="lead con delay"))),
    style("Básicos", "Más sonidos",
          ("Limpio", "Limpio Chorus", T(JC, 15, (68, 63, 60), 8, AC30, 88, mod=("chorus", 35, 22), rvb=ROOM_BIG,
                                        desc="limpio con chorus")),
          ("Crunch", "Overdrive Blues", T(TS, 45, (66, 72, 62), 15, WANGS, rvb=("spring", 40, 22),
                                          desc="overdrive con medios")),
          ("Rítmica", "Alta Ganancia", T(DS, 95, (66, 50, 70), 45, MESA, desc="metal genérico")),
          ("Variante", "Ambiental", T(JCL, 25, (66, 63, 60), 6, AC30, 88, dly=("dual", 85, 80), rvb=("cloud", 80, 40),
                                      desc="delay y reverb enormes"))),
    # bajo ------------------------------------------------------------------------------------
    style("Bajo", "Bajo limpio",
          ("Limpio", "Bajo Limpio", T(JC, 10, (55, 66, 80), 8, YAMAHA, 90, desc="bajo eléctrico, rango completo")),
          ("Limpio", "Bajo Redondo", T(JCL, 12, (50, 64, 82), 8, YAMAHA, 92, desc="dedos, grave redondo tipo Motown")),
          ("Limpio", "Bajo Púa", T(JC, 12, (76, 62, 72), 10, YAMAHA, 90, desc="con púa, ataque para rock y punk")),
          ("Variante", "Bajo Slap", T(JC, 8, (84, 46, 80), 10, YAMAHA, 90, desc="slap: agudos y graves, medios abajo"))),
    style("Bajo", "Bajo rock y metal",
          ("Crunch", "Bajo Saturado", T(TS, 40, (58, 70, 78), 10, YAMAHA, 90, desc="bajo con overdrive")),
          ("Crunch", "Bajo Rock", T(GV2, 45, (62, 70, 76), 12, YAMAHA, 90, desc="bajo de rock con gruñido")),
          ("Rítmica", "Bajo Metal", T(DS, 75, (66, 58, 74), 30, YAMAHA, 90, desc="distorsión apretada para metal")),
          ("Variante", "Bajo Fuzz", T(RAT, 85, (60, 64, 76), 18, YAMAHA, 90, desc="fuzz grueso de stoner"))),
    style("Bajo", "Bajistas",
          ("Limpio", "Steve Harris", T(JC, 14, (86, 60, 74), 10, YAMAHA, 92,
                                       desc="Iron Maiden: galope metálico con mucho agudo")),
          ("Limpio", "Flea Slap", T(JC, 10, (84, 50, 80), 10, YAMAHA, 92, desc="RHCP: slap funk")),
          ("Crunch", "Lemmy", T(JHV, 70, (78, 78, 66), 20, JVM, 92, desc="Motörhead: bajo por Marshall, como guitarra")),
          ("Rítmica", "Cliff Burton", T(RAT, 80, (66, 70, 74), 16, YAMAHA, 92,
                                        desc="Metallica: bajo distorsionado de Anesthesia"))),
    style("Bajo", "Bajo con efectos",
          ("Limpio", "Bajo Chorus", T(JC, 12, (72, 60, 68), 8, YAMAHA, 90, mod=("chorus", 40, 22),
                                      desc="chorus ochentero y post-punk")),
          ("Limpio", "Bajo Dub", T(JC, 8, (40, 58, 86), 6, YAMAHA, 90, dly=("analog", 25, 40), rvb=("spring", 30, 20),
                                   desc="reggae y dub: grave profundo")),
          ("Rítmica", "Bajo Doom", T(RAT, 110, (52, 62, 80), 26, YAMAHA, 90, desc="fuzz enorme para doom")),
          ("Solo", "Bajo Jaco", T(JC, 10, (70, 72, 64), 6, YAMAHA, 94, mod=("chorus", 20, 16), rvb=("room", 25, 16),
                                  desc="Jaco Pastorius: fretless melódico"))),
    # acústica y clásica ------------------------------------------------------------------------
    style("Acústica y clásica", "Guitarra clásica (nylon)",
          ("Limpio", "Nylon Natural", T(JC, 12, (54, 60, 62), 0, YAMAHA, 90, rvb=("room", 30, 22),
                                        desc="clásica con piezo, sonido natural")),
          ("Limpio", "Nylon Sala", T(JC, 12, (56, 60, 60), 0, YAMAHA, 90, rvb=("room", 55, 36),
                                     desc="reverb de sala de concierto")),
          ("Limpio", "Nylon Bossa", T(JC, 10, (60, 62, 56), 0, YAMAHA, 88, rvb=("room", 25, 16),
                                      desc="bossa nova y jazz suave")),
          ("Variante", "Nylon Flamenco", T(JC, 14, (68, 58, 58), 0, YAMAHA, 92, rvb=("room", 35, 24),
                                           desc="más ataque y brillo para rasgueo"))),
    style("Acústica y clásica", "Nylon con efectos",
          ("Limpio", "Nylon Chorus", T(JC, 12, (58, 60, 60), 0, YAMAHA, 90, mod=("chorus", 25, 18),
                                       rvb=("room", 35, 24), desc="nylon con chorus suave")),
          ("Variante", "Nylon Ambiente", T(JC, 12, (58, 60, 58), 0, YAMAHA, 88, dly=("dual", 35, 70),
                                           rvb=("cloud", 50, 35), desc="arpegios con delay y reverb amplia")),
          ("Limpio", "Nylon Bolero", T(JC, 12, (56, 64, 60), 0, YAMAHA, 90, rvb=("spring", 35, 24),
                                       desc="bolero y música latina")),
          ("Solo", "Nylon Solo", T(JC, 14, (60, 68, 58), 0, YAMAHA, 98, dly=("tape", 18, 55), rvb=("room", 40, 28),
                                   desc="melodía al frente con delay"))),
    style("Acústica y clásica", "Acústica de acero",
          ("Limpio", "Acústica Piezo", T(JC, 15, (52, 56, 66), 0, YAMAHA, 90, rvb=("room", 30, 24),
                                         desc="acústica con piezo, neutra")),
          ("Limpio", "Acústica Brillante", T(JC, 12, (64, 54, 60), 0, YAMAHA, 90, mod=("chorus", 12, 18),
                                             rvb=("room", 40, 28), desc="con brillo y chorus leve")),
          ("Limpio", "Acústica Strumming", T(JC, 12, (60, 52, 62), 0, YAMAHA, 90, rvb=("room", 30, 22),
                                             desc="rasgueo: medios bajos contra el graznido del piezo")),
          ("Variante", "Acústica Fingerstyle", T(JC, 12, (58, 60, 60), 0, YAMAHA, 90, dly=("analog", 12, 55),
                                                 rvb=("room", 40, 28), desc="fingerpicking con aire"))),
    style("Acústica y clásica", "Acústica con efectos",
          ("Limpio", "Acústica 12 Cuerdas", T(JC, 12, (66, 54, 58), 0, YAMAHA, 90, mod=("chorus", 35, 20),
                                              rvb=("room", 35, 24), desc="chorus que imita 12 cuerdas")),
          ("Variante", "Acústica Ambiente", T(JC, 12, (60, 56, 58), 0, YAMAHA, 88, dly=("dual", 40, 70),
                                              rvb=("cloud", 55, 38), desc="ambiental para arpegios")),
          ("Crunch", "Acústica Blues", T(TS, 28, (58, 66, 60), 4, YAMAHA, 90, rvb=("spring", 30, 22),
                                         desc="acústica algo saturada, blues del delta")),
          ("Solo", "Acústica Solo", T(JC, 14, (62, 66, 58), 0, YAMAHA, 98, dly=("tape", 18, 55), rvb=("room", 40, 28),
                                      desc="punteo al frente con delay"))),
    # stratocaster (bobinas simples) ------------------------------------------------------------
    style("Stratocaster", "Strato: limpios",
          ("Limpio", "Strato Limpio", T(JC, 18, (70, 60, 64), 10, AC210, 88, rvb=("spring", 35, 26),
                                        desc="limpio cristalino de bobinas simples")),
          ("Limpio", "Strato Posición 4", T(JCL, 26, (74, 62, 60), 10, WANGS, 88, rvb=("spring", 35, 24),
                                            desc="posición intermedia, sonido «quack»")),
          ("Limpio", "Strato Funk", T(JC, 16, (82, 58, 54), 10, AC210, 88, rvb=("room", 15, 10),
                                      desc="rasgueo funk percusivo")),
          ("Variante", "Strato Chorus 80s", T(JC, 18, (74, 58, 58), 10, AC210, 88, mod=("chorus", 40, 26),
                                              dly=("analog", 20, 55), rvb=ROOM_BIG, desc="limpio ochentero"))),
    style("Stratocaster", "Strato: blues y rock",
          ("Crunch", "Strato Blues", T(TS, 50, (70, 80, 66), 14, WANGS, 92, rvb=("spring", 35, 26),
                                       desc="Tube Screamer, medios al frente")),
          ("Crunch", "Strato Crunch", T(GV2, 55, (70, 70, 66), 16, JVM, 92, rvb=ROOM, desc="crunch británico")),
          ("Rítmica", "Strato Rock", T(JHV, 80, (70, 70, 68), 26, JVM, 92, rvb=ROOM, desc="rock con Marshall")),
          ("Solo", "Strato Solo", T(HTS, 88, (70, 80, 66), 20, JVM, 100, dly=("tape", 28, 58), rvb=("room", 30, 22),
                                    desc="lead con sustain"))),
    style("Stratocaster", "Strato: leyendas",
          ("Limpio", "Knopfler Limpio", T(JCL, 30, (76, 66, 58), 8, WANGS, 90, rvb=("room", 30, 20),
                                          desc="Dire Straits (Sultans of Swing)")),
          ("Crunch", "Mayer Neo-soul", T(TS, 40, (72, 74, 62), 10, WANGS, 90, rvb=("spring", 35, 24),
                                         desc="John Mayer: blues limpio con un poco de pelo")),
          ("Rítmica", "Blackmore", T(JHV, 82, (76, 70, 64), 24, JVM, 92, rvb=ROOM, desc="Ritchie Blackmore: Strato por Marshall")),
          ("Solo", "Eric Johnson", T(HTS, 84, (72, 76, 64), 18, WANGS, 100, dly=("analog", 25, 50), rvb=("room", 30, 22),
                                     desc="lead «violín» de Cliffs of Dover"))),
    style("Stratocaster", "Strato: surf, country y ambiente",
          ("Limpio", "Strato Surf", T(JC, 30, (84, 58, 58), 6, AC210, 90, rvb=("spring", 90, 66),
                                      desc="surf con reverb de muelle a fondo")),
          ("Limpio", "Strato Twang", T(JCL, 34, (86, 56, 56), 6, WANGS, 92, dly=("analog", 30, 14), rvb=("spring", 30, 22),
                                       desc="country con slapback")),
          ("Limpio", "Strato Tremolo", T(JC, 20, (74, 60, 60), 8, AC210, 88, mod=("tremolo", 50, 40),
                                         rvb=("spring", 40, 28), desc="trémolo vintage")),
          ("Variante", "Strato Ambiente", T(JC, 18, (72, 60, 58), 8, AC30, 86, dly=("dual", 50, 70), rvb=("cloud", 50, 35),
                                            desc="arpegios ambientales"))),
    # les paul (humbuckers) ---------------------------------------------------------------------
    style("Les Paul", "Les Paul: limpios",
          ("Limpio", "LP Jazz", T(JCL, 18, (56, 66, 64), 4, WANGS, 90, rvb=("room", 25, 16),
                                  desc="pastilla de mástil, jazz cálido")),
          ("Limpio", "LP Limpio", T(JC, 16, (74, 60, 58), 6, AC30, 88, rvb=ROOM_BIG, desc="limpio con brillo")),
          ("Limpio", "LP Arpegio", T(JC, 16, (76, 58, 56), 6, MESA, 88, mod=("chorus", 30, 22), dly=("analog", 25, 55),
                                     desc="arpegios con chorus y delay")),
          ("Variante", "LP Ambiente", T(JCL, 20, (70, 60, 58), 6, AC30, 86, dly=("dual", 50, 75), rvb=("cloud", 55, 40),
                                        desc="ambiental para baladas"))),
    style("Les Paul", "Les Paul: rock",
          ("Crunch", "LP Crunch", T(GV2, 50, (74, 70, 62), 12, JVM, 92, rvb=ROOM, desc="crunch clásico de humbucker")),
          ("Rítmica", "LP Rock", T(JHV, 72, (76, 70, 64), 20, JVM, 92, rvb=ROOM, desc="rock con Marshall")),
          ("Variante", "LP Hard Rock", T(JHV, 84, (78, 68, 66), 26, JVM, 92, rvb=ROOM, desc="hard rock con más gain")),
          ("Solo", "LP Solo", T(HTS, 88, (76, 80, 62), 20, JVM, 100, dly=("tape", 28, 58), rvb=("room", 30, 22),
                                desc="lead con sustain"))),
    style("Les Paul", "Les Paul: leyendas",
          ("Crunch", "Peter Green", T(BB, 50, (66, 70, 62), 6, WANGS, 90, rvb=("spring", 40, 28),
                                      desc="Fleetwood Mac: blues fino y dinámico")),
          ("Crunch", "Page Crunch", T(GV2, 58, (72, 70, 62), 10, JVM, 92, rvb=ROOM_BIG, desc="Jimmy Page: crunch setentero")),
          ("Rítmica", "Gibbons ZZ Top", T(GV2, 64, (72, 74, 66), 14, JVM, 92, rvb=ROOM, desc="ZZ Top: crunch texano gordo")),
          ("Solo", "Ace Frehley", T(JHV, 78, (78, 72, 64), 18, JVM, 100, dly=("analog", 20, 45), rvb=ROOM_BIG,
                                    desc="Kiss: lead de hard rock"))),
    style("Les Paul", "Les Paul: metal",
          ("Rítmica", "LP Metal", T(DS, 92, (78, 52, 72), 40, MESA, 92, desc="humbucker con alta ganancia")),
          ("Variante", "LP Thrash", T(DS, 98, (80, 46, 74), 42, MESA, 92, desc="thrash scooped")),
          ("Variante", "LP Doom", T(RAT, 96, (58, 68, 82), 24, JVM, 92, rvb=("room", 25, 14), desc="doom con fuzz")),
          ("Solo", "LP Metal Solo", T(HTS, 98, (78, 78, 64), 26, MESA, 100, dly=("tape", 28, 55), rvb=("room", 30, 22),
                                      desc="lead metal con delay"))),
    # heavy clásico -------------------------------------------------------------------------
    band("Heavy clásico", "Iron Maiden", "Maiden",
         T(JHV, 82, (75, 72, 66), 26, JVM, rvb=ROOM, desc="galope británico (The Trooper), JCM900 con medios"),
         alt=("Run to the Hills", T(JHV, 72, (72, 70, 64), 22, JVM, rvb=ROOM,
                                    desc="menos gain para que se oigan las dos guitarras")),
         clean=T(JCL, 22, (72, 64, 60), 6, JVM, 88, mod=("chorus", 40, 28), rvb=("spring", 45, 32),
                 desc="limpio británico con chorus para intros"),
         solo=T(JHV, 92, (74, 82, 64), 16, JVM, 100, dly=("analog", 28, 45), rvb=ROOM_BIG,
                desc="lead melódico con delay corto")),
    band("Heavy clásico", "Judas Priest", "Priest",
         T(JHV, 88, (78, 66, 70), 32, JVM, rvb=ROOM, desc="heavy clásico con mordida"),
         alt=("Painkiller", T(DS, 104, (84, 58, 74), 40, JVM, rvb=ROOM, desc="speed metal más saturado"))),
    band("Heavy clásico", "Dio", "Dio",
         T(JHV, 90, (76, 72, 66), 24, JVM, rvb=ROOM, desc="Marshall caliente de Vivian Campbell"),
         alt=("Holy Diver", T(JHV, 84, (74, 74, 68), 22, JVM, rvb=ROOM_BIG, desc="riff con aire y medios gruesos"))),
    band("Heavy clásico", "Ozzy Osbourne", "Ozzy",
         T(JHV, 92, (80, 74, 62), 26, JVM, rvb=ROOM, desc="Randy Rhoads: Marshall con brillo (Crazy Train)"),
         alt=("No More Tears", T(JHV, 100, (78, 70, 74), 32, MESA, rvb=ROOM, desc="Zakk Wylde, más gain y grave")),
         solo=T(HTS, 98, (76, 82, 62), 14, JVM, 100, dly=("tape", 28, 55), rvb=ROOM_BIG,
                desc="lead neoclásico de Randy con delay")),
    band("Heavy clásico", "Motörhead", "Motörhead",
         T(JHV, 100, (88, 80, 70), 26, JVM, desc="Marshall a tope, agudos y medios al frente"),
         alt=("Ace of Spades", T(JHV, 106, (90, 82, 68), 28, JVM, desc="todavía más sucio y rápido")), clean=None),
    band("Heavy clásico", "Accept", "Accept",
         T(JHV, 92, (78, 70, 70), 28, JVM, desc="heavy alemán seco (Balls to the Wall)"), clean=None),
    band("Heavy clásico", "Saxon", "Saxon",
         T(GV2, 80, (76, 72, 66), 20, JVM, rvb=ROOM, desc="crunch NWOBHM"), clean=None),
    band("Heavy clásico", "Manowar", "Manowar",
         T(JHV, 98, (74, 68, 78), 30, ENGL, rvb=ROOM, desc="heavy épico y grueso")),
    band("Heavy clásico", "Mötley Crüe", "Mötley",
         T(JHV, 86, (78, 66, 70), 24, JVM, rvb=ROOM, desc="Marshall glam (Kickstart My Heart)")),
    band("Heavy clásico", "Skid Row", "Skid Row",
         T(JHV, 90, (80, 64, 72), 26, JVM, rvb=ROOM, desc="hard rock con más gain (Youth Gone Wild)")),
    band("Heavy clásico", "Scorpions", "Scorpions",
         T(GV2, 78, (76, 70, 64), 18, JVM, rvb=ROOM, desc="crunch alemán (Rock You Like a Hurricane)")),
    band("Heavy clásico", "Def Leppard", "Leppard",
         T(HTS, 80, (78, 62, 64), 20, JVM, mod=("chorus", 20, 25), dly=("analog", 15, 40), rvb=ROOM_BIG,
           desc="distorsión pulida con chorus y delay")),
    # thrash ----------------------------------------------------------------------------------
    band("Thrash", "Metallica", "Metallica",
         T(DS, 100, (78, 40, 85), 42, MESA, rvb=("room", 15, 10), desc="thrash ochentero: medios recortados (Master of Puppets)"),
         alt=("Sandman", T(DS, 90, (72, 52, 80), 38, MESA, rvb=ROOM, desc="riff pesado y abierto, más medios (Enter Sandman)")),
         clean=T(JC, 18, (70, 60, 58), 6, MESA, 88, mod=("chorus", 35, 30), dly=("analog", 25, 55),
                 rvb=("spring", 40, 30), desc="limpio con chorus y delay (One, Fade to Black)"),
         solo=T(HTS, 104, (74, 78, 70), 30, MESA, 100, dly=("tape", 30, 60), rvb=ROOM_BIG,
                desc="Kirk Hammett: medios empujados y delay de cinta")),
    band("Thrash", "Megadeth", "Megadeth",
         T(JHV, 98, (78, 68, 72), 44, JVM, desc="rítmica precisa británica, medios presentes"),
         alt=("Symphony", T(DS, 96, (76, 60, 76), 40, JVM, rvb=ROOM, desc="Symphony of Destruction, más grueso")),
         solo=T(HTS, 102, (78, 78, 66), 30, JVM, 100, dly=("tape", 28, 55), rvb=ROOM_BIG,
                desc="Marty Friedman: lead con sustain y delay")),
    band("Thrash", "Slayer", "Slayer",
         T(DS, 116, (80, 46, 78), 50, ENGL, rvb=("room", 12, 8), desc="thrash agresivo (South of Heaven)"),
         alt=("Reign in Blood", T(DS, 118, (84, 40, 76), 50, ENGL, desc="más agudos y menos medios, muy rápido")),
         clean=T(JC, 18, (70, 56, 56), 6, ENGL, 88, mod=("chorus", 25, 20), dly=("analog", 28, 60),
                 rvb=("room", 40, 30), desc="limpio inquietante de las intros (Seasons in the Abyss)")),
    band("Thrash", "Testament", "Testament",
         T(DS, 108, (80, 58, 78), 44, MESA, desc="thrash denso de la Bay Area")),
    band("Thrash", "Anthrax", "Anthrax",
         T(JHV, 100, (82, 66, 72), 40, JVM, desc="thrash con Marshall, brillante y con medios"), clean=None),
    band("Thrash", "Exodus", "Exodus",
         T(DS, 112, (82, 52, 80), 46, MESA, desc="thrash crudo y scooped"), clean=None),
    band("Thrash", "Overkill", "Overkill",
         T(JHV, 104, (86, 62, 74), 42, JVM, desc="thrash de Nueva York, filoso"), clean=None),
    band("Thrash", "Kreator", "Kreator",
         T(DS, 118, (88, 56, 72), 50, ENGL, desc="thrash teutón brillante y agresivo")),
    band("Thrash", "Sodom", "Sodom",
         T(RAT, 114, (86, 60, 74), 44, JVM, desc="thrash crudo, casi punk"), clean=None),
    band("Thrash", "Destruction", "Destruction",
         T(DS, 114, (86, 52, 74), 48, ENGL, desc="thrash rápido y cortante"), clean=None),
    band("Thrash", "Pantera", "Pantera",
         T(DS, 112, (88, 22, 92), 48, MESA, desc="medios muy recortados, agudos filosos, graves enormes"),
         alt=("Cowboys from Hell", T(DS, 104, (84, 34, 86), 46, MESA, desc="algo menos de gain, más ataque")),
         clean=T(JC, 20, (74, 56, 58), 6, MESA, 88, mod=("chorus", 40, 26), dly=("analog", 25, 50),
                 rvb=("room", 35, 26), desc="limpio de Cemetery Gates y This Love"),
         solo=T(HTS, 110, (86, 60, 80), 36, MESA, 100, dly=("analog", 25, 45), rvb=ROOM,
                desc="Dimebag: lead chillón con delay corto")),
    band("Thrash", "Sepultura", "Sepultura",
         T(DS, 114, (80, 50, 78), 48, MESA, desc="thrash brasileño (Arise)"),
         alt=("Roots", T(DS, 112, (70, 56, 80), 50, MESA, desc="groove afinado grave, graves controlados"))),
    # death -----------------------------------------------------------------------------------
    band("Death", "Death (Chuck Schuldiner)", "Death",
         T(JHV, 104, (80, 66, 74), 42, JVM, desc="rítmica con medios, cada nota definida (Symbolic)"),
         alt=("Scream Bloody Gore", T(DS, 118, (84, 48, 80), 50, MESA, desc="death primitivo y scooped")),
         clean=T(JC, 18, (72, 60, 56), 6, MESA, 88, mod=("chorus", 30, 22), rvb=("room", 35, 26),
                 desc="limpio con chorus (Voice of the Soul)"),
         solo=T(HTS, 104, (80, 80, 66), 30, JVM, 100, dly=("tape", 25, 55), rvb=ROOM_BIG,
                desc="lead melódico de Chuck con delay")),
    band("Death", "Cannibal Corpse", "Cannibal",
         T(DS, 116, (76, 36, 84), 52, MESA, desc="brutal, scooped y apretado"), clean=None),
    band("Death", "Morbid Angel", "Morbid",
         T(DS, 118, (78, 46, 80), 52, MESA, desc="death oscuro con algo más de medios"), clean=None),
    band("Death", "Obituary", "Obituary",
         T(DS, 110, (62, 56, 86), 46, MESA, desc="death lento y pantanoso, poco agudo"), clean=None),
    band("Death", "Deicide", "Deicide",
         T(DS, 120, (82, 42, 80), 54, ENGL, desc="muy rápido, agudo y cortante"), clean=None),
    band("Death", "Entombed", "Entombed",
         T(DS, 120, (94, 80, 88), 50, ENGL, desc="sonido «motosierra» del pedal Boss HM-2"), clean=None),
    band("Death", "Dismember", "Dismember",
         T(DS, 118, (92, 78, 86), 50, ENGL, desc="motosierra sueca algo más melódica"), clean=None),
    band("Death", "At the Gates", "Gates",
         T(DS, 108, (82, 64, 74), 46, ENGL, desc="death melódico de Gotemburgo (Slaughter of the Soul)")),
    band("Death", "In Flames", "In Flames",
         T(DS, 104, (84, 62, 74), 44, V30, rvb=("room", 15, 10), desc="melodeath con armonías")),
    band("Death", "Arch Enemy", "Arch Enemy",
         T(DS, 110, (82, 58, 76), 48, ENGL, desc="rítmica moderna y precisa"),
         solo=T(HTS, 104, (80, 80, 66), 30, V30, 100, dly=("tape", 30, 55), rvb=ROOM_BIG,
                desc="Michael Amott: lead cantado con delay")),
    band("Death", "Children of Bodom", "Bodom",
         T(DS, 112, (88, 56, 74), 48, ENGL, desc="brillante y rápido para neoclásico"), clean=None),
    band("Death", "Amon Amarth", "Amon Amarth",
         T(DS, 110, (78, 62, 80), 48, ENGL, rvb=("room", 15, 10), desc="death vikingo grueso y melódico"), clean=None),
    band("Death", "Nile", "Nile",
         T(DS, 120, (80, 48, 80), 54, MESA, desc="death técnico y muy saturado")),
    band("Death", "Behemoth", "Behemoth",
         T(DS, 118, (84, 52, 78), 54, ENGL, desc="blackened death moderno"), clean=None),
    band("Death", "Bolt Thrower", "Bolt Thrower",
         T(DS, 112, (66, 64, 86), 46, MESA, desc="muro de guitarras lento y oscuro"), clean=None),
    # black -----------------------------------------------------------------------------------
    band("Black", "Darkthrone", "Darkthrone",
         T(RAT, 120, (94, 58, 48), 30, AC210, desc="crudo, fino y zumbante (lo-fi)"), clean=None),
    band("Black", "Mayhem", "Mayhem",
         T(DS, 120, (92, 54, 52), 40, V30, rvb=("room", 20, 15), desc="agudo y frío (De Mysteriis Dom Sathanas)"),
         clean=None),
    band("Black", "Emperor", "Emperor",
         T(DS, 116, (88, 58, 58), 42, ENGL, rvb=CLOUD, desc="black sinfónico con reverb amplia")),
    band("Black", "Burzum", "Burzum",
         T(RAT, 116, (90, 62, 46), 20, AC210, rvb=("cloud", 40, 25), desc="zumbido hipnótico con reverb")),
    band("Black", "Dimmu Borgir", "Dimmu",
         T(DS, 114, (84, 56, 70), 48, ENGL, rvb=ROOM, desc="black sinfónico moderno")),
    band("Black", "Dissection", "Dissection",
         T(DS, 110, (86, 62, 66), 42, V30, rvb=("room", 25, 18), desc="black melódico")),
    band("Black", "Watain", "Watain",
         T(DS, 120, (90, 56, 58), 46, V30, rvb=("room", 25, 16), desc="black ortodoxo, agresivo"), clean=None),
    # power y sinfónico -----------------------------------------------------------------------
    band("Power y sinfónico", "Blind Guardian", "Guardian",
         T(JHV, 98, (78, 70, 72), 36, ENGL, rvb=ROOM, desc="rítmica épica con medios (Valhalla, Imaginations)"),
         alt=("Mirror Mirror", T(JHV, 104, (80, 68, 74), 40, ENGL, rvb=ROOM, desc="speed power más apretado")),
         clean=T(JC, 14, (78, 56, 52), 0, YAMAHA, 86, mod=("chorus", 15, 20), rvb=("room", 45, 32),
                 desc="imitación de acústica para The Bard's Song"),
         solo=T(HTS, 100, (78, 80, 64), 30, ENGL, 100, dly=("tape", 32, 58), rvb=ROOM_BIG,
                desc="André Olbrich: lead coral con delay de cinta")),
    band("Power y sinfónico", "Helloween", "Helloween",
         T(JHV, 96, (82, 70, 70), 36, JVM, rvb=ROOM, desc="brillante y rápido (Keeper of the Seven Keys)")),
    band("Power y sinfónico", "Gamma Ray", "Gamma Ray",
         T(JHV, 98, (80, 68, 70), 36, ENGL, rvb=ROOM, desc="power con mordida")),
    band("Power y sinfónico", "Hammerfall", "Hammerfall",
         T(JHV, 96, (78, 70, 70), 34, JVM, rvb=ROOM, desc="heavy/power clásico")),
    band("Power y sinfónico", "Stratovarius", "Stratovarius",
         T(DS, 102, (84, 62, 68), 40, ENGL, rvb=ROOM, desc="power finlandés con brillo")),
    band("Power y sinfónico", "Sonata Arctica", "Sonata",
         T(DS, 100, (84, 64, 66), 38, ENGL, rvb=ROOM, desc="rítmica power ligera")),
    band("Power y sinfónico", "DragonForce", "DragonForce",
         T(DS, 106, (86, 62, 68), 42, ENGL, rvb=ROOM, desc="power a toda velocidad"),
         solo=T(HTS, 108, (86, 66, 68), 30, ENGL, 100, dly=("analog", 20, 40), rvb=ROOM_BIG,
                desc="lead de shred con delay corto")),
    band("Power y sinfónico", "Yngwie Malmsteen", "Yngwie",
         T(JHV, 92, (80, 70, 64), 26, JVM, rvb=ROOM, desc="rítmica neoclásica"),
         solo=T(HTS, 100, (80, 74, 62), 20, JVM, 100, dly=("analog", 30, 50), rvb=("room", 40, 28),
                desc="lead fluido con delay y reverb")),
    band("Power y sinfónico", "Nightwish", "Nightwish",
         T(DS, 104, (78, 62, 76), 44, ENGL, rvb=ROOM, desc="rítmica sólida bajo orquesta")),
    band("Power y sinfónico", "Epica", "Epica",
         T(DS, 108, (80, 58, 78), 46, ENGL, rvb=ROOM, desc="sinfónico pesado")),
    band("Power y sinfónico", "Kamelot", "Kamelot",
         T(JHV, 96, (78, 68, 72), 38, ENGL, rvb=("room", 25, 16), desc="power sinfónico elegante")),
    band("Power y sinfónico", "Rhapsody", "Rhapsody",
         T(JHV, 98, (80, 70, 68), 36, ENGL, rvb=ROOM_BIG, desc="power épico y cinematográfico")),
    # doom y stoner ---------------------------------------------------------------------------
    band("Doom y stoner", "Black Sabbath", "Sabbath",
         T(RAT, 88, (58, 72, 84), 18, JVM, rvb=("room", 25, 14), desc="RAT pesado, oscuro y gordo (Paranoid)"),
         alt=("Iron Man", T(RAT, 82, (56, 74, 84), 16, JVM, rvb=("room", 25, 14), desc="fuzz lento")),
         clean=T(JCL, 22, (64, 64, 62), 6, JVM, 88, mod=("phaser", 20, 14), rvb=("spring", 45, 32),
                 desc="limpio cálido (Planet Caravan, Solitude)"),
         solo=T(HTS, 92, (68, 82, 72), 14, JVM, 100, dly=("tape", 22, 50), rvb=ROOM_BIG,
                desc="Tony Iommi: lead con medios gordos")),
    band("Doom y stoner", "Candlemass", "Candlemass",
         T(DS, 98, (62, 66, 84), 32, JVM, rvb=ROOM_BIG, desc="doom épico")),
    band("Doom y stoner", "Electric Wizard", "Wizard",
         T(RAT, 122, (54, 62, 86), 30, MESA, desc="fuzz enorme y sucio"), clean=None),
    band("Doom y stoner", "Sleep", "Sleep",
         T(RAT, 118, (58, 64, 86), 28, MESA, desc="fuzz lento y grave (Dopesmoker)"), clean=None),
    band("Doom y stoner", "Kyuss", "Kyuss",
         T(RAT, 104, (60, 66, 86), 22, MESA, desc="stoner del desierto")),
    band("Doom y stoner", "Down", "Down",
         T(DS, 104, (70, 58, 86), 40, MESA, desc="groove sureño grueso")),
    band("Doom y stoner", "Black Label Society", "BLS",
         T(JHV, 106, (78, 74, 78), 36, JVM, desc="Zakk Wylde: Marshall con medios y armónicos")),
    band("Doom y stoner", "Alice in Chains", "AIC",
         T(RAT, 90, (64, 62, 80), 22, MESA, rvb=ROOM, desc="distorsión oscura con cuerpo")),
    band("Doom y stoner", "Type O Negative", "Type O",
         T(DS, 96, (62, 60, 84), 34, MESA, mod=("chorus", 40, 25), rvb=ROOM_BIG, desc="distorsión gótica con chorus")),
    # nu metal --------------------------------------------------------------------------------
    band("Nu metal", "Korn", "Korn",
         T(DS, 108, (72, 38, 80), 52, MESA, desc="7 cuerdas afinadas grave, scooped y apretado"),
         alt=("Korn Ruido", T(DS, 116, (84, 46, 78), 50, MESA, 94, mod=("phaser", 45, 40),
                              desc="ruidos y leads raros con phaser")),
         clean=T(JC, 22, (72, 56, 58), 8, MESA, 88, mod=("chorus", 40, 30), dly=("analog", 35, 50), rvb=ROOM_BIG,
                 desc="limpio inquietante con chorus y delay (Freak on a Leash, Blind)")),
    band("Nu metal", "Deftones", "Deftones",
         T(DS, 100, (70, 52, 80), 44, MESA, desc="muro grueso y oscuro"),
         clean=T(JC, 20, (70, 58, 58), 6, MESA, 86, mod=("chorus", 35, 22), dly=("dual", 35, 60), rvb=("cloud", 40, 30),
                 desc="limpio etéreo con chorus y delay")),
    band("Nu metal", "Slipknot", "Slipknot",
         T(DS, 116, (82, 44, 80), 54, MESA, desc="agresivo y apretado"),
         alt=("Duality", T(DS, 110, (80, 50, 78), 52, MESA, desc="riff con algo más de medios"))),
    band("Nu metal", "Limp Bizkit", "Limp Bizkit",
         T(DS, 106, (78, 40, 82), 50, MESA, desc="scooped y rebotón")),
    band("Nu metal", "Linkin Park", "Linkin Park",
         T(DS, 102, (80, 48, 80), 48, MESA, desc="distorsión limpia y compacta")),
    band("Nu metal", "Disturbed", "Disturbed",
         T(DS, 108, (82, 46, 78), 52, MESA, desc="staccato muy apretado")),
    band("Nu metal", "System of a Down", "SOAD",
         T(DS, 100, (74, 66, 78), 40, MESA, desc="distorsión gruesa con medios marcados")),
    band("Nu metal", "Rammstein", "Rammstein",
         T(DS, 112, (80, 56, 82), 50, ENGL, desc="muro industrial preciso")),
    band("Nu metal", "Fear Factory", "Fear Factory",
         T(DS, 116, (84, 50, 78), 54, ENGL, desc="staccato mecánico")),
    band("Nu metal", "Ministry", "Ministry",
         T(RAT, 112, (84, 58, 76), 44, MESA, desc="industrial crudo"), clean=None),
    band("Nu metal", "White Zombie", "Zombie",
         T(DS, 104, (76, 58, 82), 42, MESA, desc="groove industrial"), clean=None),
    # groove y metalcore ----------------------------------------------------------------------
    band("Groove y metalcore", "Lamb of God", "Lamb of God",
         T(DS, 108, (80, 58, 76), 50, MESA, desc="groove americano definido")),
    band("Groove y metalcore", "Machine Head", "Machine Head",
         T(DS, 110, (82, 50, 80), 50, MESA, desc="groove con armónicos")),
    band("Groove y metalcore", "Gojira", "Gojira",
         T(DS, 108, (80, 60, 78), 52, MESA, desc="pesado y orgánico")),
    band("Groove y metalcore", "Trivium", "Trivium",
         T(DS, 106, (82, 58, 76), 46, V30, desc="thrash moderno")),
    band("Groove y metalcore", "Killswitch Engage", "Killswitch",
         T(DS, 104, (82, 56, 78), 46, V30, desc="metalcore clásico")),
    band("Groove y metalcore", "Bullet for My Valentine", "BFMV",
         T(DS, 108, (84, 56, 76), 48, ENGL, desc="metalcore brillante")),
    band("Groove y metalcore", "Avenged Sevenfold", "A7X",
         T(DS, 104, (80, 64, 74), 44, MESA, desc="rítmica moderna con medios"),
         solo=T(HTS, 104, (80, 80, 66), 30, MESA, 100, dly=("tape", 28, 55), rvb=ROOM_BIG,
                desc="Synyster Gates: lead con delay")),
    style("Groove y metalcore", "Metal moderno (estilo)",
          ("Limpio", "Limpio Atmos", T(JC, 15, (74, 58, 54), 8, V30, 88, mod=("chorus", 30, 22), dly=("dual", 45, 70),
                                       rvb=("cloud", 60, 45), desc="limpio etéreo para partes calmadas")),
          ("Rítmica", "Metalcore", T(DS, 110, (84, 50, 80), 46, V30, rvb=("room", 15, 10),
                                     desc="rítmica moderna con brillo")),
          ("Variante", "Breakdown", T(DS, 114, (80, 52, 78), 55, MESA, desc="afinado grave: máximo gate")),
          ("Solo", "Lead Moderno", T(HTS, 106, (82, 76, 66), 32, V30, 100, dly=("tape", 28, 55), rvb=ROOM_BIG,
                                     desc="lead moderno con delay"))),
    # progresivo y djent ----------------------------------------------------------------------
    band("Progresivo y djent", "Dream Theater", "Petrucci",
         T(DS, 104, (80, 62, 76), 44, MESA, desc="John Petrucci: rítmica moderna Mesa"),
         alt=("Pull Me Under", T(JHV, 96, (78, 68, 74), 38, MESA, desc="rítmica prog de los 90")),
         solo=T(HTS, 106, (80, 78, 68), 32, MESA, 100, dly=("tape", 30, 58), rvb=("room", 35, 24),
                desc="lead con delay de cinta")),
    band("Progresivo y djent", "Opeth", "Opeth",
         T(DS, 108, (74, 62, 80), 46, MESA, desc="death progresivo grueso"),
         clean=T(JCL, 26, (68, 62, 58), 4, JVM, 86, mod=("chorus", 15, 18), rvb=("spring", 45, 32),
                 desc="limpio cálido de los pasajes acústicos")),
    band("Progresivo y djent", "Tool", "Tool",
         T(DS, 98, (72, 62, 80), 40, MESA, desc="Adam Jones: distorsión densa y medios")),
    band("Progresivo y djent", "Mastodon", "Mastodon",
         T(DS, 104, (76, 64, 80), 42, MESA, desc="sludge progresivo")),
    band("Progresivo y djent", "Meshuggah", "Meshuggah",
         T(DS, 118, (78, 62, 66), 54, ENGL, desc="8 cuerdas, muy apretado, graves bajo control"),
         clean=T(JC, 18, (76, 58, 52), 6, ENGL, 86, dly=("dual", 50, 70), rvb=("cloud", 55, 40),
                 desc="limpio ambiental de los interludios")),
    band("Progresivo y djent", "Periphery", "Periphery",
         T(DS, 112, (84, 60, 68), 52, V30, desc="djent brillante")),
    band("Progresivo y djent", "Animals as Leaders", "AAL",
         T(DS, 108, (84, 64, 66), 50, V30, desc="djent de 8 cuerdas definido"),
         clean=T(JC, 22, (76, 60, 52), 6, V30, 86, mod=("chorus", 25, 22), dly=("dual", 30, 60), rvb=("room", 40, 28),
                 desc="limpio prog, su sonido principal")),
    band("Progresivo y djent", "Symphony X", "Symphony X",
         T(DS, 104, (82, 64, 72), 44, ENGL, desc="prog neoclásico")),
    # gótico ----------------------------------------------------------------------------------
    band("Gótico", "Paradise Lost", "Paradise",
         T(DS, 98, (70, 64, 78), 36, JVM, rvb=ROOM_BIG, desc="doom gótico")),
    band("Gótico", "Moonspell", "Moonspell",
         T(DS, 100, (72, 62, 78), 40, ENGL, rvb=ROOM_BIG, desc="gótico portugués")),
    band("Gótico", "Katatonia", "Katatonia",
         T(DS, 96, (70, 60, 76), 38, MESA, dly=("analog", 18, 50), rvb=("room", 35, 24), desc="melancólico con delay")),
    band("Gótico", "HIM", "HIM",
         T(DS, 92, (74, 62, 76), 34, MESA, mod=("chorus", 20, 20), rvb=ROOM_BIG, desc="love metal con chorus")),
    # metal en español ------------------------------------------------------------------------
    band("Metal en español", "Rata Blanca", "Rata Blanca",
         T(JHV, 92, (76, 72, 68), 28, JVM, rvb=ROOM, desc="heavy melódico argentino"),
         solo=T(HTS, 98, (72, 80, 66), 20, JVM, 100, dly=("tape", 32, 55), rvb=("room", 35, 24),
                desc="Walter Giardino: lead con mucho sustain")),
    band("Metal en español", "Hermética", "Hermética",
         T(JHV, 98, (80, 66, 74), 38, JVM, desc="thrash/heavy argentino")),
    band("Metal en español", "Almafuerte", "Almafuerte",
         T(GV2, 84, (76, 70, 70), 26, JVM, desc="heavy rock criollo")),
    band("Metal en español", "Angra", "Angra",
         T(DS, 100, (82, 64, 70), 38, ENGL, rvb=ROOM, desc="power brasileño")),
    band("Metal en español", "Criminal", "Criminal",
         T(DS, 114, (82, 52, 78), 50, MESA, desc="thrash/death chileno"), clean=None),
    band("Metal en español", "Pentagram (Chile)", "Pentagram",
         T(DS, 116, (80, 50, 80), 52, MESA, desc="death metal chileno de la vieja escuela"), clean=None),
    band("Metal en español", "Six Magics", "Six Magics",
         T(JHV, 98, (80, 68, 70), 36, ENGL, rvb=ROOM, desc="power metal chileno")),
    band("Metal en español", "Transmetal", "Transmetal",
         T(DS, 118, (80, 46, 80), 52, MESA, desc="death/thrash mexicano"), clean=None),
    band("Metal en español", "Barón Rojo", "Barón Rojo",
         T(GV2, 80, (76, 70, 66), 20, JVM, rvb=ROOM, desc="heavy clásico español")),
    band("Metal en español", "Mägo de Oz", "Mägo de Oz",
         T(JHV, 92, (78, 68, 70), 30, JVM, rvb=("room", 25, 16), desc="folk metal")),
    band("Metal en español", "Tierra Santa", "Tierra Santa",
         T(JHV, 94, (78, 70, 70), 32, JVM, rvb=ROOM, desc="heavy épico")),
    band("Metal en español", "Avalanch", "Avalanch",
         T(DS, 100, (80, 66, 72), 36, ENGL, rvb=ROOM, desc="power/heavy")),
    # hard rock -------------------------------------------------------------------------------
    band("Hard rock", "AC/DC", "AC/DC",
         T(GV2, 55, (74, 70, 60), 10, JVM, rvb=("room", 15, 10), desc="Marshall con poco gain (Back in Black)"),
         alt=("Thunderstruck", T(JHV, 70, (76, 74, 62), 16, JVM, rvb=ROOM, desc="más gain para el tapping")),
         clean=None,
         solo=T(JHV, 76, (74, 80, 60), 12, JVM, 100, dly=("analog", 18, 40), rvb=("room", 25, 18),
                desc="Angus: lead con medios fuertes")),
    band("Hard rock", "Guns N' Roses", "GNR",
         T(JHV, 86, (76, 70, 68), 24, JVM, rvb=ROOM, desc="Les Paul por Marshall (Welcome to the Jungle)"),
         alt=("Sweet Child", T(JHV, 80, (72, 76, 64), 20, JVM, dly=("analog", 18, 40), rvb=ROOM,
                               desc="riff cantado con delay corto")),
         clean=T(JCL, 24, (66, 64, 62), 6, JVM, 88, mod=("chorus", 20, 20), rvb=("spring", 45, 32),
                 desc="limpio cálido para baladas (Patience)"),
         solo=T(HTS, 96, (70, 84, 68), 20, JVM, 100, dly=("tape", 30, 60), rvb=ROOM_BIG,
                desc="Slash: mucho sustain y medios gordos")),
    band("Hard rock", "Led Zeppelin", "Zeppelin",
         T(GV2, 62, (70, 70, 62), 10, JVM, rvb=ROOM_BIG, desc="crunch setentero con aire (Whole Lotta Love)")),
    band("Hard rock", "Van Halen", "Van Halen",
         T(JHV, 90, (72, 70, 70), 24, JVM, mod=("phaser", 30, 25), rvb=ROOM_BIG, desc="brown sound con phaser lento"),
         alt=("Eruption", T(JHV, 100, (74, 72, 66), 26, JVM, dly=("analog", 30, 40), rvb=("room", 40, 28),
                            desc="tapping con delay analógico"))),
    band("Hard rock", "Deep Purple", "Purple",
         T(GV2, 70, (74, 68, 64), 14, JVM, rvb=("room", 25, 16), desc="rock clásico con mordida británica")),
    # alternativo -----------------------------------------------------------------------------
    band("Alternativo", "Nirvana", "Nirvana",
         T(RAT, 96, (66, 50, 82), 26, MESA, desc="estribillo sucio con graves gordos (Teen Spirit)"),
         clean=T(JC, 16, (68, 56, 60), 8, MESA, 86, mod=("chorus", 45, 35), desc="limpio con chorus del verso")),
    band("Alternativo", "Pearl Jam", "Pearl Jam",
         T(GV2, 72, (72, 70, 64), 14, JVM, rvb=ROOM, desc="crunch abierto con medios (Alive)")),
    band("Alternativo", "Soundgarden", "Soundgarden",
         T(DS, 88, (64, 60, 80), 30, MESA, rvb=("room", 15, 10), desc="riff pesado y oscuro")),
    band("Alternativo", "Foo Fighters", "Foo",
         T(HTS, 86, (76, 62, 74), 28, MESA, rvb=("room", 15, 10), desc="distorsión densa y brillante (Everlong)")),
    band("Alternativo", "Muse", "Muse",
         T(RAT, 112, (74, 66, 72), 30, V30, desc="fuzz agresivo (Plug In Baby)")),
    band("Alternativo", "Arctic Monkeys", "Arctic",
         T(RAT, 78, (60, 60, 84), 18, AC30, rvb=ROOM, desc="fuzz grave y lento (Do I Wanna Know)")),
    band("Alternativo", "Radiohead", "Radiohead",
         T(RAT, 100, (74, 58, 70), 22, AC30, rvb=ROOM, desc="golpe de distorsión cruda (Creep)")),
    band("Alternativo", "Red Hot Chili Peppers", "RHCP",
         T(GV2, 48, (78, 66, 58), 10, AC30, desc="crunch seco para funk-rock (Can't Stop)"),
         alt=("Frusciante Fuzz", T(RAT, 84, (72, 74, 62), 16, AC30, rvb=ROOM, desc="fuzz cantado")),
         clean=T(JCL, 30, (82, 62, 52), 6, AC30, 88, rvb=ROOM, desc="Frusciante: limpio brillante con ataque")),
    band("Alternativo", "Soda Stereo", "Soda",
         T(TS, 55, (74, 66, 60), 10, AC30, mod=("chorus", 35, 28), rvb=ROOM_BIG, desc="Cerati: crunch con chorus ochentero"),
         clean=T(JC, 20, (74, 60, 56), 6, AC30, 86, mod=("chorus", 40, 25), dly=("analog", 30, 55),
                 rvb=("spring", 40, 30), desc="Cerati: limpio con chorus y delay")),
    band("Alternativo", "Héroes del Silencio", "Héroes",
         T(JHV, 66, (72, 70, 62), 14, JVM, dly=("tape", 30, 60), rvb=("room", 40, 28), desc="crunch épico con delay de cinta")),
    band("Alternativo", "La Ley", "La Ley",
         T(HTS, 82, (76, 62, 70), 24, MESA, rvb=ROOM, desc="distorsión noventera brillante")),
    # blues -----------------------------------------------------------------------------------
    band("Blues", "Stevie Ray Vaughan", "SRV",
         T(TS, 52, (72, 82, 62), 8, WANGS, rvb=("spring", 35, 26), desc="Tube Screamer a amplificador limpio"),
         clean=T(JCL, 34, (74, 68, 60), 4, WANGS, 88, rvb=("spring", 40, 30), desc="limpio gordo (Lenny)")),
    band("Blues", "Eric Clapton", "Clapton",
         T(BB, 70, (66, 72, 64), 8, JVM, rvb=ROOM_BIG, desc="el Bluesbreaker que da nombre al amp")),
    band("Blues", "B.B. King", "B.B. King",
         T(JCL, 40, (64, 74, 60), 6, WANGS, rvb=("spring", 40, 30), desc="limpio gordo con algo de pelo")),
    band("Blues", "Gary Moore", "Gary Moore",
         T(HTS, 80, (70, 76, 66), 18, JVM, rvb=ROOM_BIG, desc="blues rock con sustain"),
         solo=T(HTS, 88, (70, 82, 66), 16, JVM, 100, dly=("tape", 26, 60), rvb=("room", 40, 30),
                desc="lead con sustain infinito (Still Got the Blues)")),
    band("Blues", "Jimi Hendrix", "Hendrix",
         T(RAT, 76, (72, 68, 66), 12, JVM, mod=("phaser", 30, 15), rvb=ROOM, desc="fuzz por Marshall con Uni-Vibe (Voodoo Child)"),
         clean=T(JCL, 38, (70, 64, 60), 6, JVM, 88, mod=("phaser", 25, 12), rvb=("spring", 40, 30),
                 desc="limpio con vibe (Little Wing)")),
    band("Blues", "Pink Floyd (Gilmour)", "Gilmour",
         T(HTS, 82, (72, 70, 64), 16, JVM, dly=("analog", 20, 60), rvb=ROOM_BIG, desc="distorsión cálida"),
         clean=T(JC, 20, (72, 60, 56), 6, AC210, 86, mod=("chorus", 30, 25), dly=("analog", 35, 70),
                 rvb=("cloud", 45, 30), desc="limpio con chorus y delay"),
         solo=T(HTS, 90, (72, 76, 64), 14, JVM, 100, dly=("tape", 40, 75), rvb=("cloud", 55, 35),
                desc="lead con delay largo y reverb amplia (Comfortably Numb)")),
    # otros estilos (no son bandas: agrupados por tipo de sonido) -----------------------------
    style("Otros estilos", "Limpios y ambientes",
          ("Limpio", "The Edge", T(JC, 25, (78, 60, 52), 6, AC30, 88, dly=("dual", 80, 45), rvb=CLOUD,
                                   desc="U2: delay doble con figura rítmica")),
          ("Limpio", "Surf", T(JC, 30, (86, 60, 52), 4, AC210, 90, rvb=("spring", 95, 70),
                               desc="Dick Dale: reverb de muelle a fondo")),
          ("Limpio", "Reggae Skank", T(JC, 10, (80, 62, 38), 4, AC210, 88, rvb=("spring", 25, 18),
                                       desc="limpio seco y brillante, sin graves")),
          ("Variante", "Post-rock", T(JCL, 30, (72, 60, 56), 6, AC30, 86, dly=("dual", 100, 80), rvb=("cloud", 90, 60),
                                      desc="pared de delay y reverb"))),
    style("Otros estilos", "Funk, country y pop",
          ("Limpio", "Funk Nile", T(JC, 18, (86, 60, 44), 6, AC210, 88, rvb=("room", 15, 10),
                                    desc="Nile Rodgers: limpio percusivo")),
          ("Limpio", "Pop 80s", T(JC, 15, (78, 58, 52), 6, AC210, 86, mod=("chorus", 55, 30), rvb=("room", 35, 24),
                                  desc="limpio con chorus marcado")),
          ("Crunch", "Country Twang", T(JCL, 34, (88, 56, 52), 4, WANGS, 92, dly=("analog", 30, 14),
                                        rvb=("spring", 30, 22), desc="limpio brillante con slapback")),
          ("Crunch", "Rockabilly", T(TS, 40, (78, 62, 58), 6, WANGS, 92, dly=("analog", 32, 16),
                                     rvb=("spring", 40, 28), desc="crunch suave con slapback"))),
]

GENRES = list(dict.fromkeys(b.genre for b in BANKS))
