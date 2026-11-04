import type { SpeechPlayer } from '../anim/speech';
import { startClock } from './clock';
import { ScreenWatcher } from './screen';

const TURN_URL = '/speech/companion/turn';
const TICK_MS = 500;
// Share of the frame that changed between two checks, for any game or video.
const BIG_CHANGE = 0.12;
const SOME_CHANGE = 0.02;
// Below this is compression noise, not something happening.
const ANY_CHANGE = 0.005;
// Each quiet stretch lasts this multiple of its delay, so she doesn't sound like a metronome.
const JITTER_MIN = 0.85;
const JITTER_MAX = 1.25;

export type TurnReason = 'you spoke' | 'big change' | 'some change' | 'check-in' | 'idle';

export const CHATTINESS = {
  quiet: { big: 6, some: 15, any: 30, idle: 90 },
  normal: { big: 3, some: 6, any: 12, idle: 30 },
  chatty: { big: 2, some: 3, any: 6, idle: 20 },
};
export type Chattiness = keyof typeof CHATTINESS;

/**
 * Decides when she speaks. Your words always come first. Otherwise she talks regularly, and sooner
 * when more has happened on screen: delays are seconds of quiet after her last line, picked by the
 * biggest change seen since her last comment.
 */
export class Director {
  onTurn?: (reason: TurnReason) => void;
  onStopped?: () => void;

  chattiness: Chattiness = 'normal';
  /** Set while you're talking, so she doesn't start a comment over you. */
  userSpeaking = false;

  private watcher: ScreenWatcher | null = null;
  private stopClock: (() => void) | null = null;
  private lastBusyAt = 0;
  private peakChange = 0;
  private jitter = 1;
  private bigPending = false;

  constructor(private readonly speech: SpeechPlayer) {}

  get running() {
    return this.watcher !== null;
  }

  /** Starts watching. Without a stream, asks for a window, so call it from a click handler. */
  async start(stream?: MediaStream) {
    this.speech.unlock();
    const watcher = stream ? new ScreenWatcher(stream) : await ScreenWatcher.fromDisplay();
    await watcher.start();
    watcher.onChange = (fraction) => {
      this.peakChange = Math.max(this.peakChange, fraction);
    };
    watcher.onEnded = () => this.stop();
    this.watcher = watcher;
    this.peakChange = 0;
    this.bigPending = false;
    this.lastBusyAt = performance.now();
    this.rollJitter();
    this.stopClock = startClock(TICK_MS, () => this.update());
  }

  stop() {
    if (!this.watcher) return;
    this.stopClock?.();
    this.stopClock = null;
    this.watcher.stop();
    this.watcher = null;
    this.speech.stop();
    this.onStopped?.();
  }

  /** Your words always win: whatever she's saying stops. */
  say(text: string) {
    this.onTurn?.('you spoke');
    this.lastBusyAt = performance.now();
    return this.speech.playStream(TURN_URL, { kind: 'speech', text });
  }

  private update() {
    if (this.speech.active || this.userSpeaking) {
      this.lastBusyAt = performance.now();
      this.bigPending = false;
      return;
    }
    const quiet = (performance.now() - this.lastBusyAt) / 1000;
    const { reason, delay } = this.nextComment();
    if (quiet < delay * this.jitter) return;
    // Waiting one tick lets the effect behind a big change fill out before the frame is taken.
    if (reason === 'big change' && !this.bigPending) {
      this.bigPending = true;
      return;
    }
    this.comment(reason);
  }

  private nextComment(): { reason: TurnReason; delay: number } {
    const delays = CHATTINESS[this.chattiness];
    if (this.peakChange >= BIG_CHANGE) return { reason: 'big change', delay: delays.big };
    if (this.peakChange >= SOME_CHANGE) return { reason: 'some change', delay: delays.some };
    if (this.peakChange >= ANY_CHANGE) return { reason: 'check-in', delay: delays.any };
    return { reason: 'idle', delay: delays.idle };
  }

  private comment(reason: TurnReason) {
    if (!this.watcher) return;
    this.peakChange = 0;
    this.bigPending = false;
    this.rollJitter();
    this.lastBusyAt = performance.now();
    this.onTurn?.(reason);
    void this.speech.playStream(TURN_URL, { kind: 'screen', image: this.watcher.frame() });
  }

  private rollJitter() {
    this.jitter = JITTER_MIN + Math.random() * (JITTER_MAX - JITTER_MIN);
  }
}
