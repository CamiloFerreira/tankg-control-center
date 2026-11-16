// Metronome and tap tempo: port of tankg/tempo.py (tap, marking, delayTimes; checked by
// tests/ui/tools.test.mjs). The clicks are scheduled with Web Audio by the metronome sheet in app.js.
import { TEMPO } from "./data.js";

export const clamp = bpm => Math.min(TEMPO.bpmRange[1], Math.max(TEMPO.bpmRange[0], Math.floor(bpm + 0.5)));

/** BPM from tap times (seconds, oldest first): the last run without a TEMPO.tapReset pause, at most
 *  TEMPO.tapKeep taps. null until two taps. */
export function tap(times) {
  let run = [];
  for (const t of times) {
    if (run.length && t - run[run.length - 1] > TEMPO.tapReset) run = [];
    run.push(t);
  }
  run = run.slice(-TEMPO.tapKeep);
  if (run.length < 2 || run[run.length - 1] <= run[0]) return null;
  return clamp(60 * (run.length - 1) / (run[run.length - 1] - run[0]));
}

export const marking = bpm => TEMPO.markings.find(([top]) => bpm < top)[1];

/** [[note value, ms]] for a delay in time with the tempo. */
export const delayTimes = bpm => TEMPO.delayNotes.map(([name, f]) => [name, Math.floor(60000 / bpm * f + 0.5)]);
