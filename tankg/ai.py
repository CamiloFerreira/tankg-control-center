"""Create a preset from a text description with an LLM (Claude, OpenAI or any
OpenAI-compatible server such as Ollama). Standard library only (urllib), so the packaged
executable needs nothing extra.

The model fills a small "design" (effect type + amount instead of raw knob positions);
apply_design() turns it into the 21 preset bytes.
"""
from __future__ import annotations

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
    "Guitarra acústica o de nylon con pastilla piezo",
    "Bajo eléctrico",
]

AMP_INFO = [
    "J120_CL: limpio, basado en Roland JC-120, transparente, chorus estéreo",
    "J900_CL: limpio británico basado en Marshall JCM900, con pegada",
    "VAVE_TS: overdrive tipo Tube Screamer, medios marcados",
    "RAT_OD: overdrive/distorsión tipo Pro Co RAT, áspero, algo de fuzz",
    "VAVE_HTS: distorsión de alta ganancia tipo TS, densa y suave",
    "VAVE_DS: alta ganancia tipo MT-2, pesada, rítmica metal",
    "MS_GV2: distorsión británica tipo Guv'nor, rock clásico",
    "J900_HV: distorsión británica agresiva tipo JCM900, hard rock",
    "MS_HIGAIN: distorsión ligera bluesera tipo Bluesbreaker",
]
CAB_INFO = [
    "sin CAB (directo)", "AC-SeVin 2x10", "JVM 4x12 (Marshall, SM57)", "MESA 4x12 (SM57)",
    "WANGS 1x12", "VOX AC30 2x12", "HIFI YAMAHA 2x10 (rango completo, ideal acústica y bajo)",
    "ENGL 4x12", "V30 1x12 (MD421)",
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
                     "pensados para usarse juntos en una misma canción o estilo. Si la descripción no dice "
                     "otra cosa, sigue una progresión útil: A base limpia o suave, B crunch o variación, "
                     "C rítmica con más ganancia, D solo (más volumen, delay). Da a cada preset un color de "
                     "LED distinto y un nombre que lo diferencie.")

SYSTEM = f"""Eres un ingeniero de sonido experto que programa presets para la pedalera de guitarra
M-VAVE Tank-G. Devuelves SIEMPRE el preset llamando a la herramienta/esquema indicado.

Cadena de señal: NOISE GATE → AMP (TYPE, GAIN, TREBLE, MIDDLE, BASS, VOLUME) → MOD → DELAY →
REVERB → IR CAB. Cada módulo (AMP, MOD, DELAY, REVERB) puede encenderse o apagarse.

Rangos: perillas 0–127; 63 es el punto neutro del EQ (TREBLE/MIDDLE/BASS). VOLUME 85–100 es
normal. GATE 0 = apagado; 5–15 para limpios, 20–35 para distorsión, 40–55 para alta ganancia.
GAIN: limpio 10–30, crunch 35–55, distorsión 55–75, alta ganancia 75–95.

AMP (amp_type):
{chr(10).join(f"  {i}: {t}" for i, t in enumerate(AMP_INFO))}

IR CAB (cab):
{chr(10).join(f"  {i}: {t}" for i, t in enumerate(CAB_INFO))}

MOD: mod_type chorus/phaser/tremolo; mod_amount 0–100 = mezcla (chorus, tremolo) o profundidad
(phaser); mod_speed 0–127.
DELAY: dly_type analog/tape/dual; dly_mix 0–100 = cantidad de eco; dly_time 0–127 (más = eco más
largo; ~40 slapback, ~60 solo, ~80 ambiental).
REVERB: rvb_type room/spring/cloud; rvb_decay 0–100 = duración; rvb_mix 0–127 = cantidad.

Consejos: en bajo y acústica usa CAB 6 (rango completo), poca ganancia, sin delay/reverb excesivos.
Con humbuckers sube algo los agudos; con bobinas simples usa gate algo mayor contra el zumbido.
No uses reverb ni delay largos en ritmos de alta ganancia. Si el usuario nombra un artista o
canción, aproxima ese sonido con los modelos disponibles y explícalo. Responde en español."""


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
                 {"model": cfg.model, "max_tokens": 8192 if schema is BANK_SCHEMA else 2048, "system": SYSTEM,
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
            "messages": [{"role": "system", "content": SYSTEM + ("" if strict else
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
    return (f"{SYSTEM}\n\n{_user_prompt(description, instrument, bank)}\n\n"
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
