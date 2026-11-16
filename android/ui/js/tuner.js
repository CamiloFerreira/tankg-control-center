// Chromatic tuner with tunings: port of tankg/tuner.py (McLeod pitch method), same constants from data.js.
// tests/ui/tools.test.mjs checks that both give the same frequency, note and cents. It only listens:
// nothing is recorded, stored or sent.
import { TUNER } from "./data.js";

/** Average groups of samples down to about TUNER.workRate (48 kHz -> 24 kHz). */
export function downsample(samples, rate) {
  const step = Math.max(1, Math.floor(rate / TUNER.workRate));
  if (step === 1) return [Array.from(samples, Number), rate];
  const out = [];
  for (let i = 0; i + step <= samples.length; i += step) {
    let s = 0;
    for (let j = 0; j < step; j++) s += samples[i + j];
    out.push(s / step);
  }
  return [out, rate / step];
}

/** Loudness of the block in dBFS (RMS), -120 for digital silence. */
export function level(samples) {
  if (!samples.length) return -120;
  let s = 0;
  for (const v of samples) s += v * v;
  const rms = Math.sqrt(s / samples.length);
  return rms > 1e-6 ? 20 * Math.log10(rms) : -120;
}

/** Fundamental frequency in Hz of a block of samples (-1..1), null without a clear note. */
export function detect(samples, rate) {
  const [raw, r] = downsample(samples, rate);
  const n = raw.length;
  if (n < 64) return null;
  let mean = 0;
  for (const v of raw) mean += v;
  mean /= n;
  const x = raw.map(v => v - mean);
  const sq = x.map(v => v * v);
  let energy = 0;
  for (const v of sq) energy += v;
  if (energy / n < TUNER.silence * TUNER.silence) return null;
  const hi = Math.min(Math.floor(n / 2), Math.floor(r / TUNER.minHz) + 2);
  const nsdf = new Float64Array(hi + 1);
  let m = 2 * energy;
  for (let tau = 0; tau <= hi; tau++) {
    if (tau) m -= sq[n - tau] + sq[tau - 1];
    let acf = 0;
    for (let i = 0, end = n - tau; i < end; i++) acf += x[i] * x[i + tau];
    nsdf[tau] = m > 0 ? 2 * acf / m : 0;
  }
  let tau = 1;
  while (tau <= hi && nsdf[tau] > 0) tau++;   // the lobe around lag 0 is not a period
  const peaks = [];
  let bestT = -1, bestV = 0;
  for (let t = tau; t < hi; t++) {
    const v = nsdf[t];
    if (v > 0) {
      if (bestT < 0 || v > bestV) { bestT = t; bestV = v; }
    } else if (bestT >= 0) {
      peaks.push([bestT, bestV]);
      bestT = -1;
    }
  }
  if (bestT >= 0 && bestT < hi - 1) peaks.push([bestT, bestV]);
  if (!peaks.length) return null;
  const top = Math.max(...peaks.map(p => p[1]));
  if (top < TUNER.clarity) return null;
  const t = peaks.find(p => p[1] >= TUNER.peakK * top)[0];
  const a = nsdf[t - 1], b = nsdf[t], c = nsdf[t + 1];
  const den = a - 2 * b + c;
  const shift = den ? 0.5 * (a - c) / den : 0;
  const freq = r / (t + shift);
  return freq >= TUNER.minHz && freq <= TUNER.maxHz ? freq : null;
}

/** Nearest note: {name, octave, midi, cents} (cents from -50 to +50). */
export function note(freq, a4 = 440) {
  const midi = 69 + 12 * Math.log2(freq / a4);
  const n = Math.floor(midi + 0.5);
  return { name: TUNER.notes[((n % 12) + 12) % 12], octave: Math.floor(n / 12) - 1, midi: n, cents: (midi - n) * 100 };
}

/** "E2" for MIDI 40. */
export const noteName = midi => `${TUNER.notes[((midi % 12) + 12) % 12]}${Math.floor(midi / 12) - 1}`;

/** Index of the string (MIDI notes) closest to the frequency; the first one on a tie. */
export function nearestString(freq, strings, a4 = 440) {
  const midi = 69 + 12 * Math.log2(freq / a4);
  let best = 0;
  strings.forEach((m, i) => { if (Math.abs(midi - m) < Math.abs(midi - strings[best])) best = i; });
  return best;
}

/** What the tuner shows (tuner.reading in Python): chromatic with tuning 0, else the nearest string
 *  of TUNER.tunings[tuning] and the cents to it. {name, octave, cents, state, string, heard}. */
export function reading(freq, tuning = 0, a4 = 440) {
  const heard = note(freq, a4);
  const strings = TUNER.tunings[tuning]?.[1] || [];
  if (!strings.length)
    return { name: heard.name, octave: heard.octave, cents: heard.cents, state: state(heard.cents), string: -1, heard: noteName(heard.midi) };
  const i = nearestString(freq, strings, a4);
  const cents = (69 + 12 * Math.log2(freq / a4) - strings[i]) * 100;
  return { name: TUNER.notes[strings[i] % 12], octave: Math.floor(strings[i] / 12) - 1, cents, state: state(cents), string: i, heard: noteName(heard.midi) };
}

/** "ok" in tune, "low" flat (tighten), "high" sharp (loosen). */
export const state = cents => (Math.abs(cents) <= TUNER.inTune ? "ok" : cents < 0 ? "low" : "high");
