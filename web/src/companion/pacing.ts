// Share of the frame that changed within half a second, for any game or video.
export const BIG_CHANGE = 0.12;
export const SOME_CHANGE = 0.02;
// Below this is compression noise, not something happening.
export const ANY_CHANGE = 0.005;

export type TurnReason = 'you spoke' | 'big change' | 'some change' | 'check-in' | 'idle';

/** Seconds of pause after her last line before the next, by how much has happened on screen. */
export const CHATTINESS = {
  quiet: { big: 1.5, some: 10, any: 20, idle: 60 },
  normal: { big: 0.4, some: 3, any: 8, idle: 25 },
  chatty: { big: 0.2, some: 1, any: 3, idle: 15 },
};
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
}

export type Action =
  | { type: 'wait' }
  | { type: 'prepare'; reason: TurnReason; urgent: boolean; pause: number }
  | { type: 'replace'; reason: TurnReason; pause: number }
  | { type: 'play' }
  | { type: 'switch' }
  | { type: 'interrupt' };

const WAIT: Action = { type: 'wait' };

function tier(peak: number, delays: Delays): { reason: TurnReason; delay: number; urgent: boolean } {
  if (peak >= BIG_CHANGE) return { reason: 'big change', delay: delays.big, urgent: true };
  if (peak >= SOME_CHANGE) return { reason: 'some change', delay: delays.some, urgent: false };
  if (peak >= ANY_CHANGE) return { reason: 'check-in', delay: delays.any, urgent: false };
  return { reason: 'idle', delay: delays.idle, urgent: false };
}

/**
 * What to do right now. She always has her next line in preparation, and she only changes course
 * at the end of a sentence, so she never overlaps herself. Only your words can cut one short.
 */
export function nextAction(state: PacingState): Action {
  const { next, speaking } = state;

  if (next?.fromUser) {
    if (!speaking) return { type: 'play' };
    return next.ready ? { type: 'interrupt' } : WAIT;
  }
  if (state.userSpeaking) return WAIT;

  const current = tier(state.peak, state.delays);
  const pause = current.delay * state.jitter;

  if (next) {
    if (current.urgent && !state.replacedThisLine) return { type: 'replace', reason: current.reason, pause };
    if (!speaking) return state.quietFor >= next.pause ? { type: 'play' } : WAIT;
    return next.urgent && next.ready && state.hasLaterSentences ? { type: 'switch' } : WAIT;
  }

  if (state.backingOff) return WAIT;
  if (speaking && current.urgent) return { type: 'prepare', reason: current.reason, urgent: true, pause };

  const startsIn = speaking ? (state.secondsLeft === null ? Infinity : state.secondsLeft + pause) : Math.max(0, pause - state.quietFor);
  return startsIn <= state.prepareSeconds ? { type: 'prepare', reason: current.reason, urgent: current.urgent, pause } : WAIT;
}
