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


def _ask_claude(cfg: AIConfig, prompt: str) -> dict:
    data = _post(f"{cfg.base_url}/v1/messages",
                 {"x-api-key": cfg.api_key, "anthropic-version": "2023-06-01"},
                 {"model": cfg.model, "max_tokens": 2048, "system": SYSTEM,
                  "tools": [{"name": "crear_preset", "description": "Devuelve el preset de la Tank-G",
                             "input_schema": SCHEMA}],
                  "tool_choice": {"type": "tool", "name": "crear_preset"},
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


def _ask_openai(cfg: AIConfig, prompt: str, strict: bool = True) -> dict:
    headers = {"authorization": f"Bearer {cfg.api_key}"} if cfg.api_key else {}
    fmt = {"type": "json_schema", "json_schema": {"name": "preset", "schema": _without_limits(SCHEMA),
                                                    "strict": True}} \
        if strict else {"type": "json_object"}
    body = {"model": cfg.model, "response_format": fmt,
            "messages": [{"role": "system", "content": SYSTEM + ("" if strict else
                          "\nResponde solo con un objeto JSON con estas claves: " + ", ".join(SCHEMA["required"]))},
                         {"role": "user", "content": prompt}]}
    try:
        data = _post(f"{cfg.base_url}/chat/completions", headers, body)
    except AIError:
        if strict and cfg.provider == "compatible":   # many local servers lack json_schema
            return _ask_openai(cfg, prompt, strict=False)
        raise
    try:
        return json.loads(data["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError, ValueError) as e:
        raise AIError("La respuesta del modelo no era un preset JSON válido.") from e


def generate(cfg: AIConfig, description: str, instrument: str, like: Preset | None = None) -> tuple[Preset, str, str]:
    """Returns (preset, name, explanation)."""
    cfg = cfg.resolved()
    if cfg.provider != "compatible" and not cfg.api_key:
        raise AIError(f"Falta la clave de API de {PROVIDERS[cfg.provider]['label']}.")
    prompt = f"Instrumento: {instrument}\nSonido deseado: {description.strip()}"
    design = _ask_claude(cfg, prompt) if cfg.provider == "claude" else _ask_openai(cfg, prompt)
    missing = [k for k in SCHEMA["required"] if k not in design]
    if missing:
        raise AIError(f"Al preset de la IA le faltan campos: {', '.join(missing)}")
    try:
        preset = apply_design(design, like)
    except (TypeError, ValueError) as e:
        raise AIError(f"Valores no válidos en la respuesta de la IA: {e}") from e
    return preset, str(design["name"])[:40], str(design["explanation"])


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
