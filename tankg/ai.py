"""Create a preset from a text description with an LLM (Claude, OpenAI or any
OpenAI-compatible server such as Ollama). Standard library only (urllib), so the packaged
executable needs nothing extra.

The model fills a small "design" (effect type + amount instead of raw knob positions);
apply_design() turns it into the 21 preset bytes.
"""
from __future__ import annotations

import functools
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

from .model import AMP_MODELS, CAB_MODELS, FIELD_BY_KEY, Preset

# Browser mode: no API key, the user pastes the prompt in a chat web page and copies the answer.
WEB_SITES = {
    "Claude": "https://claude.ai/new",
    "ChatGPT": "https://chatgpt.com/",
    "Gemini": "https://gemini.google.com/app",
}

PROVIDERS = {
    "claude": {"label": "Claude (Anthropic)", "model": "claude-sonnet-5-5",
               "url": "https://api.anthropic.com", "env": "ANTHROPIC_API_KEY"},
    "openai": {"label": "ChatGPT (OpenAI)", "model": "gpt-4.1-mini",
               "url": "https://api.openai.com/v1", "env": "OPENAI_API_KEY"},
    "compatible": {"label": "Compatible con OpenAI (Ollama, LM Studio…)", "model": "llama3.1",
                   "url": "http://localhost:11434/v1", "env": ""},
}

INSTRUMENTS = [
    "Guitarra eléctrica con humbuckers (tipo Les Paul)",
    "Guitarra eléctrica con bobinas simples (tipo Stratocaster)",
    "Guitarra clásica de nylon con pastilla piezo",
    "Guitarra acústica de cuerdas de acero con pastilla piezo",
    "Bajo eléctrico",
]

# Model descriptions from the official preset list, plus usage notes (what the emulated gear
# is known for); index = byte value.
AMP_INFO = [
    "J120_CL: limpio basado en Roland JC-120. Transparente, brillante, no distorsiona. Limpios de "
    "funk, pop, new wave, arpegios con chorus, limpios de metal moderno y nu metal.",
    "J900_CL: canal limpio del Marshall JCM900. Limpio con más cuerpo y medios; con GAIN alto se "
    "ensucia un poco. Limpios de rock/blues, intros de hard rock y heavy, country.",
    "VAVE_TS: overdrive tipo Ibanez Tube Screamer. Joroba de medios, poco grave, suave. Blues "
    "(SRV), crunch ligero, rock en español ochentero, rockabilly.",
    "RAT_OD: Pro Co RAT. Áspero, con fuzz, mucho cuerpo. Grunge, stoner, doom, sludge, black metal "
    "crudo, fuzz de Hendrix, rock alternativo, Muse.",
    "VAVE_HTS: distorsión de alta ganancia basada en TS. Densa, suave y comprimida, con sustain. "
    "Solos (Gilmour, Slash, Gary Moore, power metal), leads melódicos, distorsión noventera.",
    "VAVE_DS: alta ganancia tipo Boss MT-2 Metal Zone. Pesada, rítmica, ataque apretado. Thrash, "
    "death, black, groove, nu metal, metalcore, djent: casi toda rítmica de metal extremo.",
    "MS_GV2: distorsión británica tipo Marshall Guv'nor. Crunch clásico con dinámica. AC/DC, "
    "Zeppelin, Deep Purple, rock clásico, Pearl Jam.",
    "J900_HV: canal de distorsión del Marshall JCM900. Agresiva, medios presentes. Hard rock, "
    "heavy británico (Iron Maiden, Judas Priest), Van Halen, Guns N' Roses, power y speed metal, "
    "death metal de la vieja escuela, Zakk Wylde.",
    "MS_HIGAIN: Marshall Bluesbreaker. Distorsión ligera y bluesera (pese al nombre no es alta "
    "ganancia). Clapton, blues rock, crunch transparente.",
]
CAB_INFO = [
    "sin CAB (directo): solo para amplificador real o equipo con su propia simulación; suena áspero "
    "en auriculares o PA",
    "AC-SeVin 2x10 (tipo Fender Vibrolux): brillante y ligero; limpios, surf, funk, reggae",
    "JVM 4x12 (Marshall 1960 con SM57): medios británicos; rock clásico, hard rock, heavy, thrash británico",
    "MESA 4x12 (Rectifier con SM57): grave grande y apretado; metal moderno, nu metal, thrash americano, death",
    "WANGS 1x12 (combo americano): cálido y abierto; blues, country, rockabilly",
    "VOX AC30 2x12 (Alnico Blue): chime y medios-agudos; britpop, rock alternativo, Cerati, The Edge",
    "HIFI YAMAHA 2x10: rango completo y plano; ideal para acústica con piezo y bajo",
    "ENGL 4x12 (V30): moderno, agresivo y definido; metal europeo, power, death melódico, djent, industrial",
    "V30 1x12 (con MD421): medios-agudos con mordida; metalcore, leads modernos, black metal",
]

ZONES = {"mod": ("chorus", "phaser", "tremolo"), "dly": ("analog", "tape", "dual"),
         "rvb": ("room", "spring", "cloud")}

SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Nombre corto del preset (máx. 20 caracteres)"},
        "explanation": {"type": "string", "description": "Explicación breve en español de las decisiones"},
        "amp_on": {"type": "boolean"},
        "amp_type": {"type": "integer", "minimum": 0, "maximum": 8},
        "gain": {"type": "integer", "minimum": 0, "maximum": 127},
        "treble": {"type": "integer", "minimum": 0, "maximum": 127},
        "middle": {"type": "integer", "minimum": 0, "maximum": 127},
        "bass": {"type": "integer", "minimum": 0, "maximum": 127},
        "volume": {"type": "integer", "minimum": 0, "maximum": 127},
        "gate": {"type": "integer", "minimum": 0, "maximum": 127},
        "cab": {"type": "integer", "minimum": 0, "maximum": 8},
        "mod_on": {"type": "boolean"},
        "mod_type": {"type": "string", "enum": list(ZONES["mod"])},
        "mod_amount": {"type": "integer", "minimum": 0, "maximum": 100},
        "mod_speed": {"type": "integer", "minimum": 0, "maximum": 127},
        "dly_on": {"type": "boolean"},
        "dly_type": {"type": "string", "enum": list(ZONES["dly"])},
        "dly_mix": {"type": "integer", "minimum": 0, "maximum": 100},
        "dly_time": {"type": "integer", "minimum": 0, "maximum": 127},
        "rvb_on": {"type": "boolean"},
        "rvb_type": {"type": "string", "enum": list(ZONES["rvb"])},
        "rvb_decay": {"type": "integer", "minimum": 0, "maximum": 100},
        "rvb_mix": {"type": "integer", "minimum": 0, "maximum": 127},
        "led_color": {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 255},
                      "minItems": 3, "maxItems": 3, "description": "Color RGB del LED del interruptor"},
    },
    "required": ["name", "explanation", "amp_on", "amp_type", "gain", "treble", "middle", "bass",
                 "volume", "gate", "cab", "mod_on", "mod_type", "mod_amount", "mod_speed", "dly_on",
                 "dly_type", "dly_mix", "dly_time", "rvb_on", "rvb_type", "rvb_decay", "rvb_mix",
                 "led_color"],
    "additionalProperties": False,
}

BANK_SCHEMA = {
    "type": "object",
    "properties": {
        "bank_name": {"type": "string", "description": "Nombre corto del banco (máx. 16 caracteres)"},
        "presets": {"type": "array", "items": SCHEMA, "minItems": 4, "maxItems": 4,
                    "description": "Exactamente 4 presets, en orden A, B, C, D"},
    },
    "required": ["bank_name", "presets"],
    "additionalProperties": False,
}

BANK_INSTRUCTIONS = ("Crea un BANCO de 4 presets (A, B, C, D) coherentes entre sí para esa descripción, "
                     "pensados para usarse juntos en una misma canción o estilo: mismo CAB y EQ parecido "
                     "salvo que haya motivo. Si es una banda, cubre sus sonidos más reconocibles (rítmica "
                     "principal, limpio o intro, variación de otra época o canción, solo) y nombra cada "
                     "preset por la canción o la parte. Si la descripción no dice otra cosa, sigue una "
                     "progresión útil: A limpio o suave, B crunch o variación, C rítmica con más ganancia, "
                     "D solo (VOLUME 6–10 más alto, medios arriba, delay tape). Da a cada preset un color "
                     "de LED distinto y un nombre que lo diferencie.")

SYSTEM = f"""Eres un ingeniero de sonido experto en guitarra que programa presets para la
pedalera M-VAVE Tank-G. Conoces el equipo (amplificador, pedales, pastillas, afinación) que usan
los guitarristas conocidos y lo traduces a los controles de la Tank-G. Devuelves SIEMPRE el preset
llamando a la herramienta/esquema indicado.

CADENA DE SEÑAL: NOISE GATE → AMP (TYPE, GAIN, TREBLE, MIDDLE, BASS, VOLUME) → MOD → DELAY →
REVERB → IR CAB. AMP, MOD, DELAY y REVERB se encienden o apagan por separado.

MÉTODO (síguelo en orden):
1. Identifica estilo, época, guitarrista, guitarra/pastillas y equipo original. Si nombran una
   canción, piensa en la parte concreta (riff, verso limpio, estribillo, solo).
2. Elige el AMP que más se parezca al amplificador o pedal original (guía abajo). El TYPE define
   el carácter de la distorsión; GAIN solo ajusta la cantidad dentro de ese carácter.
3. Elige el IR CAB según el gabinete original y el estilo.
4. Fija GAIN según la categoría (escala de abajo). Más ganancia no es más pesado: las rítmicas de
   metal suenan más definidas con algo menos de gain que un solo.
5. Ecualiza respecto de 63 (neutro) en pasos de 5–25: «scooped» = MIDDLE 25–45 con TREBLE y BASS
   altos; británico/solo = MIDDLE 70–85; oscuro = TREBLE 50–60; brillante = TREBLE 75–90.
6. GATE según ganancia y ruido. VOLUME entre 85 y 100 (los solos 6–10 por encima de la rítmica
   del mismo banco para que destaquen).
7. Efectos solo si son característicos del sonido pedido; en rítmicas de alta ganancia, sin delay
   y con reverb corta (o nada).

ESCALAS (0–127):
- GAIN: limpio 10–30 · crunch 40–65 · distorsión 65–90 · alta ganancia 90–110 · extremo 110–125.
- GATE: 0 = apagado; limpio 0–8; crunch 8–16; distorsión 16–30; alta ganancia 30–45; metal extremo,
  djent o afinaciones graves 45–55 (más alto corta las notas).
- TREBLE/MIDDLE/BASS: 63 = neutro. BASS > 90 enturbia, sobre todo con afinaciones graves.
- VOLUME: 85–100 normal.
- Los presets de fábrica de M-VAVE usan GAIN 47–114 y TREBLE 57–101: valores altos no son raros.

AMP (amp_type):
{chr(10).join(f"  {i}: {t}" for i, t in enumerate(AMP_INFO))}

IR CAB (cab):
{chr(10).join(f"  {i}: {t}" for i, t in enumerate(CAB_INFO))}

EFECTOS (cada perilla de tipo elige entre tres efectos; tú das el tipo y una cantidad 0–100):
- MOD: mod_type chorus|phaser|tremolo; mod_amount 0–100 = mezcla (chorus, tremolo) o
  profundidad (phaser); mod_speed 0–127 (15–30 lento tipo Uni-Vibe o chorus ochentero, 60+ rápido).
- DELAY: dly_type analog (cálido, oscuro) | tape (eco de cinta, solos) | dual (patrones rítmicos,
  ambiental); dly_mix 0–100 = cantidad; dly_time 0–127 (≈15 slapback rockabilly/country, ≈40
  doblaje corto, ≈55–65 solo, ≈80+ ambiental/post-rock).
- REVERB: rvb_type room (natural, corta) | spring (muelle de combo: surf, limpios vintage) | cloud
  (enorme, ambiental, black atmosférico); rvb_decay 0–100 = duración; rvb_mix 0–127 = cantidad.

GUÍA POR ESTILO (punto de partida; ajusta al artista concreto):
- Limpio pop/funk: J120_CL, gain 10–25, treble 75–88, bass 40–55, AC-SeVin/VOX; chorus opcional.
- Blues: VAVE_TS (SRV) o MS_HIGAIN (Clapton), gain 45–70, middle 72–85, WANGS/JVM, spring.
- Rock clásico y hard rock: MS_GV2 (crunch) o J900_HV (más gain), gain 55–90, middle 66–76, JVM.
- Heavy clásico/NWOBHM: J900_HV, gain 75–95, middle 66–80, JVM, gate 20–30.
- Thrash: VAVE_DS (americano, scooped: middle 35–50, MESA) o J900_HV (británico/alemán: middle
  60–72, JVM/ENGL), gain 95–118, gate 40–50.
- Death metal: VAVE_DS, gain 110–122, gate 45–55. Florida (Death, Morbid Angel, Cannibal Corpse):
  middle 35–55, MESA/ENGL. Sueco «chainsaw» HM-2 (Entombed, Dismember): treble 88–98, middle 75–85,
  bass 85–92. Melódico (At the Gates, In Flames, Arch Enemy): middle 55–70, ENGL/V30.
- Black metal: VAVE_DS o RAT_OD, gain 110–125, treble 85–98, bass 45–60 (fino y zumbante),
  V30/ENGL o AC-SeVin para lo crudo; reverb cloud 35–60 en lo atmosférico.
- Power/sinfónico (Blind Guardian, Helloween, Stratovarius, Nightwish): J900_HV o VAVE_DS,
  gain 90–110, middle 62–75, ENGL/JVM; solos con VAVE_HTS + delay tape.
- Doom/stoner/sludge: RAT_OD (fuzz) o VAVE_DS, gain 85–120, treble 50–62, bass 85–95, MESA/JVM.
- Nu metal (Korn, Deftones, Slipknot, Limp Bizkit): VAVE_DS, gain 100–115, middle 30–50, bass
  85–95, MESA, gate 45–55; limpios con J120_CL, chorus/delay.
- Groove/metalcore/djent: VAVE_DS, gain 100–122, gate 45–55, ENGL/V30/MESA; djent middle 55–65 y
  bass 60–70 para que se entiendan las notas graves.
- Progresivo (Dream Theater, Opeth, Tool): VAVE_DS/J900_HV gain 90–110 middle 60–72; leads con
  VAVE_HTS + delay.
- Grunge/alternativo: RAT_OD, gain 80–100, middle 45–60; limpios con chorus.
- Ambiental/post-rock: J120_CL o J900_CL, delay dual mix 60–100, reverb cloud.

LO QUE LA TANK-G NO TIENE (aproxímalo y dilo en la explicación): wah fijo → MIDDLE 78–90 y TREBLE
alto; fuzz → RAT_OD; boost/TS delante de un amp → elige el amp con más medios y GATE algo mayor;
compresor → menos GAIN y algo más de VOLUME; octavador, pitch, flanger o EQ gráfico → no existen,
elige lo más cercano (flanger ≈ phaser lento y profundo).

INSTRUMENTO: humbuckers (Les Paul) ya dan salida alta (gain 5–10 menos, treble +3–8; pastilla de
mástil = sonido de jazz, treble 52–60); bobinas simples (Stratocaster) piden gate +5–10 y un poco
más de gain/bass; acústica con piezo: J120_CL o J900_CL, gain 10–20, CAB HIFI YAMAHA, gate 0–5,
sin distorsión salvo que la pidan. Nylon (clásica): treble 52–62, reverb room más larga (sala de
concierto). Acero: middle 50–58 para quitar el «graznido» del piezo, chorus leve imita 12 cuerdas.
Bajo: CAB HIFI YAMAHA, gain 8–15 limpio (40–75 saturado), bass 72–86, slap = treble alto y middle
bajo, gate 8–30 según ganancia; sin delay ni modulación salvo que lo pidan. Afinaciones graves (drop C, B, 7 cuerdas): BASS ≤ 80 y
GATE más alto.

SALIDA: «name» corto (máx. 20 caracteres), reconocible («Puppets Rítmica», «Trooper»).
«explanation» en español, 2–4 frases: qué equipo original emula, por qué ese AMP/CAB, y un consejo
práctico (pastilla, volumen de la guitarra o qué perilla tocar si suena demasiado sucio/oscuro).
«led_color»: un color que identifique el preset (rojo distorsión, azul/cian limpio, amarillo
crunch, rosa/morado solo o ambiental).
{{references}}"""


def _references() -> str:
    """Calibrated examples from the built-in band library, as the model must return them."""
    from . import artists   # artists imports this module
    picks = ["Metallica Rítmica", "Metallica Limpio", "AC/DC Rítmica", "SRV Rítmica", "Gilmour Solo",
             "Cannibal Rítmica", "Entombed Rítmica", "Korn Rítmica", "Guardian Rítmica", "Darkthrone Rítmica",
             "The Edge"]
    by_name = {p.name: (b, p) for b in artists.BANKS for p in b.presets}
    lines = []
    for name in picks:
        if name in by_name:
            bank, p = by_name[name]
            design = {k: v for k, v in p.design().items() if k != "led_color"}
            lines.append(f"- {p.name} [{p.role}] ({p.desc}): "
                         + json.dumps(design, ensure_ascii=False, separators=(",", ":")))
    return ("\nEJEMPLOS CALIBRADOS (presets de la biblioteca de la app, en el formato de salida):\n"
            + "\n".join(lines)) if lines else ""


@functools.cache
def system_prompt() -> str:
    return SYSTEM.replace("{references}", _references())


class AIError(Exception):
    """Error with a message meant for the user."""


@dataclass
class AIConfig:
    provider: str = "claude"
    api_key: str = ""
    model: str = ""
    base_url: str = ""

    def resolved(self) -> "AIConfig":
        p = PROVIDERS[self.provider]
        key = self.api_key or (os.environ.get(p["env"], "") if p["env"] else "")
        return AIConfig(self.provider, key, self.model or p["model"], (self.base_url or p["url"]).rstrip("/"))


def _zone_value(zone: int, amount: int) -> int:
    """Knob position inside one third of a three-zone knob, keeping clear of the dead spots
    between zones (zone limits assumed to be equal thirds, unverified)."""
    lo, hi = zone * 128 // 3 + 4, (zone + 1) * 128 // 3 - 5
    return lo + round(max(0, min(100, amount)) * (hi - lo) / 100)


def _clamp(key: str, value) -> int:
    return max(0, min(FIELD_BY_KEY[key].maximum, int(value)))


def apply_design(design: dict, like: Preset | None = None) -> Preset:
    """Turn the model's design into a preset; unmapped bytes are kept from `like`."""
    p = like.copy() if like is not None else Preset(bytearray(21))
    for key in ("amp_type", "gain", "treble", "middle", "bass", "volume", "gate", "cab",
                "mod_speed", "dly_time", "rvb_mix"):
        p.set(key, _clamp(key, design[key]))
    for key in ("amp_on", "mod_on", "dly_on", "rvb_on"):
        p.set(key, 1 if design[key] else 0)
    for prefix, field, amount in (("mod", "mod_fx", "mod_amount"), ("dly", "dly_mix", "dly_mix"),
                                  ("rvb", "rvb_decay", "rvb_decay")):
        zone = ZONES[prefix].index(design[f"{prefix}_type"]) if design[f"{prefix}_type"] in ZONES[prefix] else 0
        p.set(field, _zone_value(zone, int(design[amount])))
    color = design.get("led_color") or [255, 255, 255]
    p.color = tuple(max(0, min(255, int(c))) for c in (list(color) + [255, 255, 255])[:3])
    return p


def _post(url: str, headers: dict, body: dict, timeout: float = 120) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"content-type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read()).get("error", {})
            detail = detail.get("message", detail) if isinstance(detail, dict) else detail
        except (ValueError, AttributeError):
            detail = ""
        hint = {401: "clave de API inválida", 403: "sin permiso para este modelo",
                404: "modelo o URL no encontrados", 429: "límite de uso o saldo agotado"}.get(e.code, "")
        raise AIError(f"Error {e.code} del servicio de IA{': ' + hint if hint else ''}. {detail}".strip()) from e
    except urllib.error.URLError as e:
        raise AIError(f"No se pudo conectar con {url}: {e.reason}") from e
    except TimeoutError as e:
        raise AIError("El servicio de IA tardó demasiado en responder.") from e


def _ask_claude(cfg: AIConfig, prompt: str, schema: dict = SCHEMA) -> dict:
    tool = "crear_banco" if schema is BANK_SCHEMA else "crear_preset"
    data = _post(f"{cfg.base_url}/v1/messages",
                 {"x-api-key": cfg.api_key, "anthropic-version": "2023-06-01"},
                 {"model": cfg.model, "max_tokens": 8192 if schema is BANK_SCHEMA else 2048, "system": system_prompt(),
                  "tools": [{"name": tool, "description": "Devuelve el resultado para la Tank-G",
                             "input_schema": schema}],
                  "tool_choice": {"type": "tool", "name": tool},
                  "messages": [{"role": "user", "content": prompt}]})
    for block in data.get("content", []):
        if block.get("type") == "tool_use":
            return block["input"]
    raise AIError("La respuesta de Claude no contenía un preset.")


def _without_limits(schema):
    """OpenAI strict mode rejects some keywords (minimum, maxItems…); values are clamped locally."""
    if isinstance(schema, dict):
        return {k: _without_limits(v) for k, v in schema.items()
                if k not in ("minimum", "maximum", "minItems", "maxItems")}
    return schema


def _ask_openai(cfg: AIConfig, prompt: str, strict: bool = True, schema: dict = SCHEMA) -> dict:
    headers = {"authorization": f"Bearer {cfg.api_key}"} if cfg.api_key else {}
    fmt = {"type": "json_schema", "json_schema": {"name": "preset", "schema": _without_limits(schema),
                                                    "strict": True}} \
        if strict else {"type": "json_object"}
    body = {"model": cfg.model, "response_format": fmt,
            "messages": [{"role": "system", "content": system_prompt() + ("" if strict else
                          "\nResponde solo con un objeto JSON con estas claves: " + ", ".join(schema["required"])
                          + ("; cada elemento de presets con: " + ", ".join(SCHEMA["required"])
                             if schema is BANK_SCHEMA else ""))},
                         {"role": "user", "content": prompt}]}
    try:
        data = _post(f"{cfg.base_url}/chat/completions", headers, body)
    except AIError:
        if strict and cfg.provider == "compatible":   # many local servers lack json_schema
            return _ask_openai(cfg, prompt, strict=False, schema=schema)
        raise
    try:
        return json.loads(data["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError, ValueError) as e:
        raise AIError("La respuesta del modelo no era un preset JSON válido.") from e


def _build(design: dict, like: Preset | None) -> tuple[Preset, str, str]:
    missing = [k for k in SCHEMA["required"] if k not in design]
    if missing:
        raise AIError(f"Al preset de la IA le faltan campos: {', '.join(missing)}")
    try:
        preset = apply_design(design, like)
    except (TypeError, ValueError) as e:
        raise AIError(f"Valores no válidos en la respuesta de la IA: {e}") from e
    return preset, str(design["name"])[:40], str(design["explanation"])


def _build_bank(doc: dict, likes: list[Preset | None]) -> tuple[str, list[tuple[Preset, str, str]]]:
    designs = doc.get("presets")
    if not isinstance(designs, list) or len(designs) < 4:
        raise AIError("La IA no devolvió los 4 presets del banco.")
    return str(doc.get("bank_name") or "")[:24], [_build(d, like) for d, like in zip(designs[:4], likes)]


def _checked(cfg: AIConfig) -> AIConfig:
    cfg = cfg.resolved()
    if cfg.provider != "compatible" and not cfg.api_key:
        raise AIError(f"Falta la clave de API de {PROVIDERS[cfg.provider]['label']}.")
    return cfg


def _user_prompt(description: str, instrument: str, bank: bool) -> str:
    return (f"Instrumento: {instrument}\nSonido deseado: {description.strip()}"
            + (f"\n\n{BANK_INSTRUCTIONS}" if bank else ""))


def generate(cfg: AIConfig, description: str, instrument: str, like: Preset | None = None) -> tuple[Preset, str, str]:
    """One preset: returns (preset, name, explanation)."""
    cfg = _checked(cfg)
    prompt = _user_prompt(description, instrument, False)
    design = _ask_claude(cfg, prompt) if cfg.provider == "claude" else _ask_openai(cfg, prompt)
    return _build(design, like)


def generate_bank(cfg: AIConfig, description: str, instrument: str,
                  likes: list[Preset | None]) -> tuple[str, list[tuple[Preset, str, str]]]:
    """A bank of 4: returns (bank name, [(preset, name, explanation)] for A..D)."""
    cfg = _checked(cfg)
    prompt = _user_prompt(description, instrument, True)
    doc = _ask_claude(cfg, prompt, BANK_SCHEMA) if cfg.provider == "claude" else \
        _ask_openai(cfg, prompt, schema=BANK_SCHEMA)
    return _build_bank(doc, likes)


def describe(preset: Preset) -> str:
    """Human summary of a preset (for the result view)."""
    g = preset.get

    def onoff(k):
        return "ON" if g(k) else "off"
    return (f"AMP {onoff('amp_on')}: {AMP_MODELS[g('amp_type')]} · GAIN {g('gain')} · TREBLE {g('treble')} · "
            f"MIDDLE {g('middle')} · BASS {g('bass')} · VOLUME {g('volume')}\n"
            f"GATE {g('gate')} · CAB {CAB_MODELS[g('cab')]}\n"
            f"MOD {onoff('mod_on')}: FX {g('mod_fx')} SPEED {g('mod_speed')} · "
            f"DELAY {onoff('dly_on')}: MIX {g('dly_mix')} TIME {g('dly_time')} · "
            f"REVERB {onoff('rvb_on')}: DECAY {g('rvb_decay')} MIX {g('rvb_mix')}")


def web_prompt(description: str, instrument: str, bank: bool = False) -> str:
    """Self-contained prompt for a chat web page (browser mode)."""
    keys = ", ".join(f'"{k}"' for k in SCHEMA["required"])
    shape = (f'un objeto con "bank_name" (texto) y "presets": una lista de EXACTAMENTE 4 objetos (A, B, C, D), '
             f"cada uno con exactamente estas claves: {keys}") if bank else \
        f"exactamente estas claves: {keys}"
    return (f"{system_prompt()}\n\n{_user_prompt(description, instrument, bank)}\n\n"
            "Responde ÚNICAMENTE con un bloque de código JSON (```json ... ```) que contenga "
            f"{shape}. Tipos: amp_on/mod_on/dly_on/rvb_on booleanos; mod_type uno de "
            "chorus|phaser|tremolo; dly_type uno de analog|tape|dual; rvb_type uno de room|spring|cloud; "
            "led_color lista [R, G, B] de 0 a 255; el resto números enteros en los rangos indicados; "
            "name y explanation en español.")


def _json_candidates(text: str) -> list:
    import re
    found = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    start = text.find("{")
    if start >= 0:
        depth = 0
        for i, ch in enumerate(text[start:], start):
            depth += ch == "{"
            depth -= ch == "}"
            if depth == 0:
                found.append(text[start:i + 1])
                break
    docs = []
    for c in found:
        try:
            docs.append(json.loads(c))
        except ValueError:
            continue
    return [d for d in docs if isinstance(d, dict)]


def parse_bank_text(text: str) -> dict | None:
    """Find a bank JSON ({"bank_name", "presets": [4]}) in a chat answer."""
    for doc in _json_candidates(text):
        presets = doc.get("presets")
        if isinstance(presets, list) and len(presets) >= 4 and \
                all(isinstance(p, dict) and all(k in p for k in SCHEMA["required"]) for p in presets[:4]):
            return doc
    return None


def bank_from_text(text: str, likes: list[Preset | None]) -> tuple[str, list[tuple[Preset, str, str]]]:
    doc = parse_bank_text(text)
    if doc is None:
        raise AIError("No encontré los 4 presets del banco en el texto copiado. Copia la respuesta completa.")
    return _build_bank(doc, likes)


def parse_design_text(text: str) -> dict | None:
    """Find the preset JSON in a chat answer (fenced or bare). None if there is none."""
    return next((d for d in _json_candidates(text) if all(k in d for k in SCHEMA["required"])), None)


def from_text(text: str, like: Preset | None = None) -> tuple[Preset, str, str]:
    """Browser mode: build the preset from the copied chat answer."""
    design = parse_design_text(text)
    if design is None:
        raise AIError("No encontré el preset en el texto copiado. Copia la respuesta completa de la IA "
                      "(el bloque JSON).")
    try:
        preset = apply_design(design, like)
    except (TypeError, ValueError) as e:
        raise AIError(f"Valores no válidos en la respuesta de la IA: {e}") from e
    return preset, str(design["name"])[:40], str(design["explanation"])
