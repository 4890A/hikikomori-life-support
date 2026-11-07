// Share of the frame that changed within half a second, for any game or video.
export const BIG_CHANGE = 0.12;
export const SOME_CHANGE = 0.02;
// Below this is compression noise, not something happening.
export const ANY_CHANGE = 0.005;

export type TurnReason = 'you spoke' | 'big change' | 'some change' | 'check-in' | 'idle' | 'greeting';

/**
 * How much she talks. target: the share of the last 90 s she may spend talking. base: the breath
 * after a line, to which 0.4 s per second of that line is added. some and any: more seconds on top
 * for smaller changes. idle: seconds of quiet before she talks about nothing in particular.
 */
export const CHATTINESS = {
  quiet: { target: 0.15, base: 4, some: 6, any: 14, idle: 150 },
  normal: { target: 0.33, base: 2.5, some: 2, any: 8, idle: 60 },
  chatty: { target: 0.45, base: 1.2, some: 0.5, any: 3, idle: 30 },
};
// Even a big moment leaves this much quiet after her last line, plus a little per second of it.
const MIN_BIG_PAUSE = 0.6;
const BIG_PAUSE_PER_LINE_SECOND = 0.15;
const PAUSE_PER_LINE_SECOND = 0.4;
// Past the target she only reacts to big moments; past this many times it, only to you.
const OVER_TARGET = 1.3;
// After this many lines in a row without you saying anything, she waits twice as long.
const RUN_LIMIT = 2;
// After she asks you something, she waits this long for an answer, and only a big moment after 2 s.
export const ANSWER_WAIT_SECONDS = 6;
const ANSWER_BIG_AFTER_SECONDS = 2;
export type Chattiness = keyof typeof CHATTINESS;
export type Delays = (typeof CHATTINESS)[Chattiness];

export interface NextLine {
  ready: boolean;
  /** A reaction to a big change, which may cut her current line short at a sentence end. */
  urgent: boolean;
  fromUser: boolean;
  /** Seconds of quiet to leave before it plays. */
  pause: number;
}

export interface PacingState {
  /** Generating or making sound for the current line. */
  speaking: boolean;
  /** Seconds until she finishes, or null while more of her line may still arrive. */
  secondsLeft: number | null;
  hasLaterSentences: boolean;
  /** Seconds since she last spoke. */
  quietFor: number;
  /** The biggest change since the frame behind the newest line. */
  peak: number;
  next: NextLine | null;
  /** A prepared line was already replaced during this line, so don't do it again. */
  replacedThisLine: boolean;
  userSpeaking: boolean;
  /** How long a line usually takes to be ready. */
  prepareSeconds: number;
  /** Still waiting after a failure. */
  backingOff: boolean;
  delays: Delays;
  /** Random multiple of each pause, so she doesn't sound like a metronome. */
  jitter: number;
  /** Share of the last 90 s she spent talking, from 0 to 1. */
  talkShare: number;
  /** How long her last line lasted, in seconds. */
  lastLineSeconds: number;
  /** Her lines in a row since you last said anything. */
  unpromptedRun: number;
  /** Her last line asked you something. */
  askedYou: boolean;
}

export type Action =
  | { type: 'wait' }
  | { type: 'prepare'; reason: TurnReason; urgent: boolean; pause: number }
  | { type: 'replace'; reason: TurnReason; pause: number }
  | { type: 'play' }
  | { type: 'switch' }
  | { type: 'interrupt' };

const WAIT: Action = { type: 'wait' };

/** What she may say now, and after how much quiet. Null when she should leave the floor to you. */
function tier(state: PacingState): { reason: TurnReason; delay: number; urgent: boolean } | null {
  const { peak, delays } = state;
  const big = peak >= BIG_CHANGE;
  if (state.talkShare >= delays.target * OVER_TARGET) return null;
  const overTarget = state.talkShare >= delays.target;
  if (overTarget && !big) return null;
  if (state.askedYou && state.quietFor < ANSWER_WAIT_SECONDS && !(big && state.quietFor >= ANSWER_BIG_AFTER_SECONDS)) return null;

  const breath = delays.base + PAUSE_PER_LINE_SECOND * state.lastLineSeconds;
  const run = state.unpromptedRun >= RUN_LIMIT ? 2 : 1;
  if (big) {
    // Over the target a big moment still counts, but it waits its turn like any other line.
    if (overTarget) return { reason: 'big change', delay: breath * run, urgent: false };
    return { reason: 'big change', delay: (MIN_BIG_PAUSE + BIG_PAUSE_PER_LINE_SECOND * state.lastLineSeconds) * run, urgent: true };
  }
  if (peak >= SOME_CHANGE) return { reason: 'some change', delay: (breath + delays.some) * run, urgent: false };
  if (peak >= ANY_CHANGE) return { reason: 'check-in', delay: (breath + delays.any) * run, urgent: false };
  return { reason: 'idle', delay: Math.max(breath, delays.idle) * run, urgent: false };
}

/**
 * What to do right now. She prepares her next line so it's ready when her pause ends, and she only
 * changes course at the end of a sentence, so she never overlaps herself. Only your words can cut
 * one short. She keeps to a share of the talking, breathes between lines, and waits for your answers.
 */
export function nextAction(state: PacingState): Action {
  const { next, speaking } = state;

  if (next?.fromUser) {
    if (!speaking) return { type: 'play' };
    return next.ready ? { type: 'interrupt' } : WAIT;
  }
  if (state.userSpeaking) return WAIT;

  const current = tier(state);
  const pause = (current?.delay ?? 0) * state.jitter;

  if (next) {
    if (current?.urgent && !state.replacedThisLine) return { type: 'replace', reason: current.reason, pause };
    if (!speaking) return state.quietFor >= next.pause ? { type: 'play' } : WAIT;
    return next.urgent && next.ready && state.hasLaterSentences ? { type: 'switch' } : WAIT;
  }

  if (state.backingOff || !current) return WAIT;
  if (speaking && current.urgent) return { type: 'prepare', reason: current.reason, urgent: true, pause };

  const startsIn = speaking ? (state.secondsLeft === null ? Infinity : state.secondsLeft + pause) : Math.max(0, pause - state.quietFor);
  return startsIn <= state.prepareSeconds ? { type: 'prepare', reason: current.reason, urgent: current.urgent, pause } : WAIT;
}
