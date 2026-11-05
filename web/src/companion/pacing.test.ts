import { describe, expect, it } from 'vitest';
import { BIG_CHANGE, CHATTINESS, nextAction, SOME_CHANGE, type NextLine, type PacingState } from './pacing';

const state = (overrides: Partial<PacingState> = {}): PacingState => ({
  speaking: false,
  secondsLeft: 0,
  hasLaterSentences: false,
  quietFor: 0,
  peak: 0,
  next: null,
  replacedThisLine: false,
  userSpeaking: false,
  prepareSeconds: 1.5,
  backingOff: false,
  delays: CHATTINESS.normal,
  jitter: 1,
  ...overrides,
});

const line = (overrides: Partial<NextLine> = {}): NextLine => ({ ready: false, urgent: false, fromUser: false, pause: 0.4, ...overrides });

describe('preparing her next line', () => {
  it('waits while the line is long and nothing much is happening', () => {
    expect(nextAction(state({ speaking: true, secondsLeft: 6, peak: SOME_CHANGE })).type).toBe('wait');
  });

  it('starts early enough for the next line to follow on time', () => {
    // 3 s pause after a line ending in 0: start preparing 1.5 s before it would begin.
    expect(nextAction(state({ quietFor: 1.4, peak: SOME_CHANGE })).type).toBe('wait');
    expect(nextAction(state({ quietFor: 1.6, peak: SOME_CHANGE })).type).toBe('prepare');
  });

  it('prepares while still talking, near the end of a line', () => {
    const action = nextAction(state({ speaking: true, secondsLeft: 0.4, peak: BIG_CHANGE - 0.01, delays: CHATTINESS.chatty }));
    expect(action).toMatchObject({ type: 'prepare', reason: 'some change', urgent: false });
  });

  it('does not count on a line that is still being written', () => {
    expect(nextAction(state({ speaking: true, secondsLeft: null, peak: SOME_CHANGE })).type).toBe('wait');
  });

  it('reacts to a big change at once, however long her line has left', () => {
    expect(nextAction(state({ speaking: true, secondsLeft: 6, peak: BIG_CHANGE }))).toMatchObject({ type: 'prepare', urgent: true });
    expect(nextAction(state({ speaking: true, secondsLeft: null, peak: BIG_CHANGE }))).toMatchObject({ type: 'prepare', urgent: true });
  });

  it('comments eventually on an unchanging screen', () => {
    expect(nextAction(state({ quietFor: 20 })).type).toBe('wait');
    expect(nextAction(state({ quietFor: 24 }))).toMatchObject({ type: 'prepare', reason: 'idle' });
  });

  it('holds off after a failure', () => {
    expect(nextAction(state({ quietFor: 100, backingOff: true })).type).toBe('wait');
  });

  it('follows the chattiness setting', () => {
    const peak = SOME_CHANGE;
    expect(nextAction(state({ quietFor: 2, peak, delays: CHATTINESS.quiet })).type).toBe('wait');
    expect(nextAction(state({ quietFor: 2, peak, delays: CHATTINESS.chatty })).type).toBe('prepare');
  });
});

describe('playing the next line', () => {
  it('leaves its pause after she finishes', () => {
    expect(nextAction(state({ quietFor: 0.2, next: line({ ready: true }) })).type).toBe('wait');
    expect(nextAction(state({ quietFor: 0.5, next: line({ ready: true }) })).type).toBe('play');
  });

  it('never starts over her current line without a sentence end to switch at', () => {
    const action = nextAction(state({ speaking: true, secondsLeft: 1, next: line({ ready: true, urgent: true }), hasLaterSentences: false, replacedThisLine: true }));
    expect(action.type).toBe('wait');
  });

  it('plays even before audio is ready once it is time, so her face can react first', () => {
    expect(nextAction(state({ quietFor: 1, next: line({ ready: false }) })).type).toBe('play');
  });
});

describe('changing course', () => {
  it('switches at a sentence end for a ready reaction', () => {
    expect(nextAction(state({ speaking: true, next: line({ ready: true, urgent: true }), hasLaterSentences: true })).type).toBe('switch');
  });

  it('carries on if the reaction is not ready yet, so there is no silence', () => {
    expect(nextAction(state({ speaking: true, next: line({ ready: false, urgent: true }), hasLaterSentences: true })).type).toBe('wait');
  });

  it('does not cut her line short for an ordinary next line', () => {
    expect(nextAction(state({ speaking: true, next: line({ ready: true, urgent: false }), hasLaterSentences: true })).type).toBe('wait');
  });
});

describe('replacing a stale line', () => {
  it('replaces a prepared line when something big happens', () => {
    expect(nextAction(state({ speaking: true, peak: BIG_CHANGE, next: line({ ready: true }) }))).toMatchObject({ type: 'replace', reason: 'big change' });
  });

  it('replaces at most once per line, however busy the screen is', () => {
    const action = nextAction(state({ speaking: true, peak: BIG_CHANGE, next: line({ ready: true, urgent: true }), hasLaterSentences: true, replacedThisLine: true }));
    expect(action.type).toBe('switch');
  });

  it('keeps a line through small changes', () => {
    expect(nextAction(state({ speaking: true, peak: SOME_CHANGE, next: line({ ready: true }) })).type).toBe('wait');
  });
});

describe('your words', () => {
  it('interrupt her as soon as the reply is ready', () => {
    expect(nextAction(state({ speaking: true, next: line({ fromUser: true, ready: true }) })).type).toBe('interrupt');
  });

  it('let her keep talking until then, so there is no gap', () => {
    expect(nextAction(state({ speaking: true, next: line({ fromUser: true, ready: false }) })).type).toBe('wait');
  });

  it('play at once when she is quiet', () => {
    expect(nextAction(state({ quietFor: 0, next: line({ fromUser: true, ready: false }) })).type).toBe('play');
  });

  it('are not replaced by a big change', () => {
    expect(nextAction(state({ speaking: true, peak: BIG_CHANGE, next: line({ fromUser: true }) })).type).toBe('wait');
  });

  it('keep her from starting a comment while you are talking', () => {
    expect(nextAction(state({ userSpeaking: true, quietFor: 100, peak: BIG_CHANGE })).type).toBe('wait');
  });
});
