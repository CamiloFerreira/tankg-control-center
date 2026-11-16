"""Metronome and tap tempo, the same on the desktop (dialogs.MetronomeDialog, clicks rendered into a
Qt audio stream by ClickTrack) and in the APK (metronome sheet in app.js, clicks scheduled with Web
Audio; android/ui/js/tempo.js repeats tap(), marking() and delay_times(), checked by
tests/ui/tools.test.mjs).

The delay times are for setting the pedal's DLY TIME by ear: how the DLY TIME byte maps to
milliseconds is not verified (research/FINDINGS.md), so the app never writes a tempo into a preset."""
from __future__ import annotations

import math

BPM_RANGE = (30, 300)
DEFAULT_BPM = 120
# [name, beats per bar]; the first beat of the bar is accented (none with one beat)
METERS = [["4/4", 4], ["3/4", 3], ["2/4", 2], ["6/8", 6], ["5/4", 5], ["7/8", 7], ["Sin acento", 1]]
TAP_RESET = 2.0   # seconds without a tap start a new count
TAP_KEEP = 6      # taps averaged (the last ones)
CLICK = {"hz": 1000, "accentHz": 1600, "ms": 30}
DELAY_HINT = ("Ajusta a oído el DLY TIME de la pedalera con estos tiempos. La app no lo cambia sola: la relación entre "
              "la perilla y los milisegundos todavía no está verificada.")
# Italian tempo markings: [up to this BPM (exclusive), name]
MARKINGS = [[60, "Largo"], [66, "Larghetto"], [76, "Adagio"], [108, "Andante"], [120, "Moderato"],
            [156, "Allegro"], [176, "Vivace"], [200, "Presto"], [10_000, "Prestissimo"]]
# Note values for the delay: [name, fraction of a beat (quarter note)]
DELAY_NOTES = [["Negra", 1.0], ["Corchea con puntillo", 0.75], ["Corchea", 0.5], ["Tresillo de corchea", 1 / 3],
               ["Semicorchea", 0.25]]


def clamp(bpm: float) -> int:
    return int(min(BPM_RANGE[1], max(BPM_RANGE[0], math.floor(bpm + 0.5))))


def tap(times: list[float]) -> int | None:
    """BPM from the times of the taps (seconds, oldest first): the last run of taps without a pause
    of TAP_RESET, at most TAP_KEEP of them. None until there are two taps in a run."""
    run = []
    for t in times:
        if run and t - run[-1] > TAP_RESET:
            run = []
        run.append(t)
    run = run[-TAP_KEEP:]
    if len(run) < 2 or run[-1] <= run[0]:
        return None
    return clamp(60 * (len(run) - 1) / (run[-1] - run[0]))


def marking(bpm: float) -> str:
    return next(name for top, name in MARKINGS if bpm < top)


def delay_times(bpm: float) -> list[list]:
    """[[note value, milliseconds]] for a delay in time with the tempo."""
    beat = 60000 / bpm
    return [[name, math.floor(beat * f + 0.5)] for name, f in DELAY_NOTES]


def click(rate: int, accent: bool) -> list[float]:
    """One click: a short sine burst with an exponential decay."""
    hz = CLICK["accentHz"] if accent else CLICK["hz"]
    n = int(rate * CLICK["ms"] / 1000)
    amp = 0.8 if accent else 0.55
    return [amp * math.sin(2 * math.pi * hz * i / rate) * math.exp(-5 * i / n) for i in range(n)]


class ClickTrack:
    """Renders the metronome sample by sample (desktop), so every click lands on its exact sample
    whatever the timer jitter: render(n) returns the next n samples; `clicks` lists (sample, beat) of
    the clicks rendered, for the beat lights."""

    def __init__(self, rate: int, bpm: float, beats: int):
        self.rate = rate
        self.bpm, self.beats = bpm, max(1, beats)
        self.pos = 0              # first sample of the next render
        self.next_click = 0.0     # sample where the next click starts
        self.beat = 0             # its place in the bar
        self.tail: list[float] = []   # end of a click that did not fit in the last block
        self.clicks: list[tuple[int, int]] = []
        self._sounds = {True: click(rate, True), False: click(rate, False)}

    def set(self, bpm: float | None = None, beats: int | None = None) -> None:
        """Takes effect from the next click."""
        if bpm is not None:
            self.bpm = bpm
        if beats is not None:
            self.beats = max(1, beats)
            self.beat %= self.beats

    def render(self, n: int) -> list[float]:
        out = [0.0] * n
        for i, v in enumerate(self.tail[:n]):
            out[i] += v
        self.tail = self.tail[n:]
        end = self.pos + n
        while self.next_click < end:
            start = int(self.next_click)
            sound = self._sounds[self.beat == 0 and self.beats > 1]
            offset = start - self.pos
            fit = sound[:n - offset]
            for i, v in enumerate(fit):
                out[offset + i] += v
            if len(fit) < len(sound):
                rest = sound[len(fit):]
                self.tail = [a + b for a, b in zip(rest, self.tail + [0.0] * len(rest))] + self.tail[len(rest):]
            self.clicks.append((start, self.beat))
            del self.clicks[:-32]
            self.next_click += self.rate * 60 / self.bpm
            self.beat = (self.beat + 1) % self.beats
        self.pos = end
        return out

    def beat_at(self, sample: int) -> tuple[int, int] | None:
        """(beat, sample where it started) of the last click at or before `sample`."""
        last = None
        for start, beat in self.clicks:
            if start <= sample:
                last = (beat, start)
        return last
