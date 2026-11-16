"""Chromatic tuner shared by the desktop (dialogs.TunerDialog, audio through Qt Multimedia) and the APK
(android/ui/js/tuner.js, Web Audio): the pitch of a block of samples with the McLeod pitch method
(normalized square difference function, first peak close to the highest one, parabolic
interpolation), then the note and the cents against A4. It only listens: nothing is recorded,
stored or sent, and the pedal is not involved (the input is the computer's or phone's microphone,
or the Tank-G's own USB audio). Chromatic by default (the nearest semitone); with a tuning from
TUNINGS the reading is against the nearest string of that tuning, so a string several semitones away
(E -> D for Drop D) shows how far it is. tuner.js repeats the same steps and tests/ui/tools.test.mjs
checks that both give the same result."""
from __future__ import annotations

import math
from operator import mul

NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
# [name, MIDI note of each string from the lowest]; the first one is the chromatic tuner (no strings)
TUNINGS = [
    ["Cromático", []],
    ["Guitarra estándar (E A D G B E)", [40, 45, 50, 55, 59, 64]],
    ["Medio tono abajo (Eb)", [39, 44, 49, 54, 58, 63]],
    ["Un tono abajo (D)", [38, 43, 48, 53, 57, 62]],
    ["Drop D (D A D G B E)", [38, 45, 50, 55, 59, 64]],
    ["Drop C# (C# G# C# F# A# D#)", [37, 44, 49, 54, 58, 63]],
    ["Drop C (C G C F A D)", [36, 43, 48, 53, 57, 62]],
    ["Drop B (B F# B E G# C#)", [35, 42, 47, 52, 56, 61]],
    ["C estándar (C F A# D# G C)", [36, 41, 46, 51, 55, 60]],
    ["DADGAD", [38, 45, 50, 55, 57, 62]],
    ["Open G (D G D G B D)", [38, 43, 50, 55, 59, 62]],
    ["Open D (D A D F# A D)", [38, 45, 50, 54, 57, 62]],
    ["Open E (E B E G# B E)", [40, 47, 52, 56, 59, 64]],
    ["7 cuerdas (B E A D G B E)", [35, 40, 45, 50, 55, 59, 64]],
    ["Bajo 4 cuerdas (E A D G)", [28, 33, 38, 43]],
    ["Bajo 5 cuerdas (B E A D G)", [23, 28, 33, 38, 43]],
]
FRAME = 4096        # samples per analysis (~90 ms at 44.1/48 kHz: almost three periods of a bass low B)
WORK_RATE = 22050   # blocks are averaged down to about this rate before the analysis
MIN_HZ = 27.0       # below the low B of a five-string bass (30.9 Hz)
MAX_HZ = 1100.0     # above the 12th fret of the high E
SILENCE = 0.002     # RMS under this (about -54 dBFS) is silence: no note
CLARITY = 0.6       # the best peak must be this periodic (1 = perfect) to show a note
PEAK_K = 0.9        # the first peak at least this fraction of the best one is the period
IN_TUNE = 3         # cents either side that count as in tune
A4_RANGE = (430, 450)
STATE_TEXT = {"ok": "Afinada", "low": "Baja: tensa la cuerda", "high": "Alta: afloja la cuerda"}
WAITING = "Toca una cuerda al aire"
PRIVACY = "Solo escucha mientras está abierto: el sonido no se graba ni se envía."


def downsample(samples, rate: float) -> tuple[list[float], float]:
    """Average groups of samples down to about WORK_RATE (48 kHz -> 24 kHz); the analysis cost grows
    with the square of the length."""
    step = max(1, int(rate // WORK_RATE))
    if step == 1:
        return [float(v) for v in samples], float(rate)
    out = [sum(samples[i:i + step]) / step for i in range(0, len(samples) - step + 1, step)]
    return out, rate / step


def level(samples) -> float:
    """Loudness of the block in dBFS (RMS), -120 for digital silence."""
    if not len(samples):
        return -120.0
    rms = math.sqrt(sum(v * v for v in samples) / len(samples))
    return 20 * math.log10(rms) if rms > 1e-6 else -120.0


def detect(samples, rate: float) -> float | None:
    """Fundamental frequency in Hz of a block of samples (floats in -1..1), None when there is no
    clear note (silence, noise, chords)."""
    x, r = downsample(samples, rate)
    n = len(x)
    if n < 64:
        return None
    mean = sum(x) / n
    x = [v - mean for v in x]
    sq = [v * v for v in x]
    energy = sum(sq)
    if energy / n < SILENCE * SILENCE:
        return None
    hi = min(n // 2, int(r / MIN_HZ) + 2)
    nsdf = [0.0] * (hi + 1)
    m = 2 * energy
    for tau in range(hi + 1):
        if tau:
            m -= sq[n - tau] + sq[tau - 1]
        acf = sum(map(mul, x[:n - tau], x[tau:]))
        nsdf[tau] = 2 * acf / m if m > 0 else 0.0
    tau = 1
    while tau <= hi and nsdf[tau] > 0:   # the lobe around lag 0 is not a period
        tau += 1
    peaks: list[tuple[int, float]] = []
    best_t, best_v = -1, 0.0
    for t in range(tau, hi):
        v = nsdf[t]
        if v > 0:
            if best_t < 0 or v > best_v:
                best_t, best_v = t, v
        elif best_t >= 0:
            peaks.append((best_t, best_v))
            best_t = -1
    if best_t >= 0 and best_t < hi - 1:
        peaks.append((best_t, best_v))
    if not peaks:
        return None
    top = max(v for _, v in peaks)
    if top < CLARITY:
        return None
    t = next(t for t, v in peaks if v >= PEAK_K * top)
    a, b, c = nsdf[t - 1], nsdf[t], nsdf[t + 1]
    den = a - 2 * b + c
    shift = 0.5 * (a - c) / den if den else 0.0
    freq = r / (t + shift)
    return freq if MIN_HZ <= freq <= MAX_HZ else None


def note(freq: float, a4: float = 440.0) -> dict:
    """Nearest note: {"name": "E", "octave": 2, "midi": 40, "cents": -3.2} (cents from -50 to +50)."""
    midi = 69 + 12 * math.log2(freq / a4)
    n = math.floor(midi + 0.5)
    return {"name": NOTES[n % 12], "octave": n // 12 - 1, "midi": n, "cents": (midi - n) * 100}


def note_name(midi: int) -> str:
    """"E2" for MIDI 40."""
    return f"{NOTES[midi % 12]}{midi // 12 - 1}"


def nearest_string(freq: float, strings: list[int], a4: float = 440.0) -> int:
    """Index of the string (MIDI notes) closest to the frequency; the first one on a tie."""
    midi = 69 + 12 * math.log2(freq / a4)
    best = 0
    for i, m in enumerate(strings):
        if abs(midi - m) < abs(midi - strings[best]):
            best = i
    return best


def reading(freq: float, tuning: int = 0, a4: float = 440.0) -> dict:
    """What the tuner shows. Chromatic (tuning 0): the nearest note and the cents to it. With a tuning:
    the target string (the nearest one) and the cents to it, which can go beyond ±50.
    {"name", "octave", "cents", "state", "string" (index, -1 when chromatic), "heard" ("F2")}."""
    heard = note(freq, a4)
    strings = TUNINGS[tuning][1] if 0 <= tuning < len(TUNINGS) else []
    if not strings:
        return {"name": heard["name"], "octave": heard["octave"], "cents": heard["cents"],
                "state": state(heard["cents"]), "string": -1, "heard": note_name(heard["midi"])}
    i = nearest_string(freq, strings, a4)
    cents = (69 + 12 * math.log2(freq / a4) - strings[i]) * 100
    return {"name": NOTES[strings[i] % 12], "octave": strings[i] // 12 - 1, "cents": cents, "state": state(cents),
            "string": i, "heard": note_name(heard["midi"])}


def state(cents: float) -> str:
    """"ok" in tune, "low" flat (tighten), "high" sharp (loosen)."""
    return "ok" if abs(cents) <= IN_TUNE else "low" if cents < 0 else "high"
