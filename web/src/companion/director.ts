import type { PreparedLine, SpeechPlayer } from '../anim/speech';
import { startClock } from './clock';
import type { ShareSource } from './desktopGaze';
import { BIG_CHANGE, CHATTINESS, nextAction, type Action, type Chattiness, type TurnReason } from './pacing';
import { ScreenWatcher } from './screen';

export { CHATTINESS, type Chattiness, type TurnReason };

const TURN_URL = '/speech/companion/turn';
const COMMIT_URL = '/speech/companion/commit';
// Often enough that a big change is acted on as soon as the watcher sees it.
const TICK_MS = 33;
const JITTER_MIN = 0.85;
const JITTER_MAX = 1.25;
// How long a line takes to be ready, until recent lines say otherwise.
const START_PREPARE_SECONDS = 1.5;
// Leaves room for a slower line than usual, since being early costs nothing.
const PREPARE_MARGIN_SECONDS = 0.3;
const ESTIMATE_WEIGHT = 0.3;
const FAILURE_BACKOFF_MS = 2000;
// After she looks and finds nothing worth saying, before looking again.
const DECLINED_BACKOFF_MS = 5000;

interface Upcoming {
  line: PreparedLine;
  urgent: boolean;
  fromUser: boolean;
  pause: number;
}

/**
 * Decides when she speaks. She keeps watching and preparing while she talks, so her next line is
 * ready when this one ends, and changes course at a sentence end if something big happens. See
 * pacing.ts for the rules.
 */
export class Director {
  /** A line is starting. `frame` is the image she was sent, and `said` your words, if any. */
  onTurn?: (reason: TurnReason, frame: string | null, said: string | null) => void;
  onStopped?: () => void;
  /** A line she was preparing couldn't be made. */
  onProblem?: (message: string) => void;
  /** What's being shared changed, or stopped. */
  onShare?: (source: ShareSource | null) => void;

  chattiness: Chattiness = 'normal';
  /** Set while you're talking, so she doesn't start a comment over you. */
  userSpeaking = false;
  /** How many prepared lines were thrown away for fresher ones, for the panel. */
  replacedCount = 0;
  /** How many times she looked and chose to say nothing, and what she saw last time. */
  declinedCount = 0;
  lastSeen: string | null = null;

  private watcher: ScreenWatcher | null = null;
  private upcoming: Upcoming | null = null;
  private lastBusyAt = 0;
  private peakChange = 0;
  private jitter = 1;
  private replacedThisLine = false;
  private glanced = false;
  private aboutScreen = false;
  private backoffUntil = 0;
  private prepareSeconds = START_PREPARE_SECONDS;

  constructor(private readonly speech: SpeechPlayer) {
    speech.onLineDone = (line) => this.commit(line);
    // Always running, so your typed messages work with or without a shared window.
    startClock(TICK_MS, () => this.update());
  }

  get running() {
    return this.watcher !== null;
  }

  /** The line being prepared to follow the current one. */
  get nextLine() {
    return this.upcoming?.line ?? null;
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
    this.onShare?.(watcher.source);
    this.peakChange = 0;
    this.lastBusyAt = performance.now();
    this.rollJitter();
  }

  stop() {
    if (!this.watcher) return;
    this.watcher.stop();
    this.watcher = null;
    this.dropUpcoming();
    this.speech.stop();
    this.speech.watchScreen(false);
    this.onShare?.(null);
    this.onStopped?.();
  }

  /** Your words come first: her reply starts as soon as it's ready, and her voice fades into it. */
  say(text: string) {
    this.dropUpcoming();
    // The screen as you spoke, so she can answer 「これ何？」 ("What's this?").
    const image = this.watcher?.frame();
    const line = this.speech.prepare(TURN_URL, { kind: 'speech', text, image }, { reason: 'you spoke', frame: image ?? null, said: text });
    this.upcoming = { line, urgent: true, fromUser: true, pause: 0 };
    this.update();
  }

  private update() {
    this.speech.poll();
    if (!this.watcher && !this.upcoming) return;
    const speaking = this.speech.active;
    this.speech.watchScreen(speaking && this.aboutScreen);
    if (speaking || this.userSpeaking) this.lastBusyAt = performance.now();
    this.dropIfUnusable();
    if (speaking && this.peakChange >= BIG_CHANGE && !this.glanced) {
      this.glanced = true;
      this.speech.glance();
    }
    const { upcoming } = this;
    this.act(
      nextAction({
        speaking,
        secondsLeft: this.speech.secondsLeft,
        hasLaterSentences: this.speech.hasLaterSentences,
        quietFor: (performance.now() - this.lastBusyAt) / 1000,
        peak: this.peakChange,
        next: upcoming && { ready: upcoming.line.ready, urgent: upcoming.urgent, fromUser: upcoming.fromUser, pause: upcoming.pause },
        replacedThisLine: this.replacedThisLine,
        userSpeaking: this.userSpeaking,
        prepareSeconds: this.prepareSeconds,
        backingOff: performance.now() < this.backoffUntil,
        delays: CHATTINESS[this.chattiness],
        jitter: this.jitter,
      }),
    );
  }

  private act(action: Action) {
    switch (action.type) {
      case 'wait':
        return;
      case 'prepare':
        this.prepare(action.reason, action.urgent, action.pause);
        return;
      case 'replace':
        this.dropUpcoming();
        this.replacedCount += 1;
        this.replacedThisLine = true;
        this.prepare(action.reason, true, action.pause);
        return;
      case 'play':
        this.startUpcoming((line) => this.speech.play(line));
        return;
      case 'switch':
        this.startUpcoming((line) => this.speech.switchTo(line));
        return;
      case 'interrupt':
        this.startUpcoming((line) => this.speech.fadeInto(line));
        return;
    }
  }

  private prepare(reason: TurnReason, urgent: boolean, pause: number) {
    if (!this.watcher) return;
    this.peakChange = 0;
    // Only what changes after this picture counts next.
    this.watcher.rebase();
    this.glanced = false;
    this.rollJitter();
    const frame = this.watcher.frame();
    const nowSaying = this.speech.saying || undefined;
    const line = this.speech.prepare(TURN_URL, { kind: 'screen', image: frame, now_saying: nowSaying, reason }, { reason, frame, said: null });
    this.upcoming = { line, urgent, fromUser: false, pause };
  }

  private startUpcoming(start: (line: PreparedLine) => void) {
    const { upcoming } = this;
    if (!upcoming) return;
    this.upcoming = null;
    this.replacedThisLine = false;
    this.aboutScreen = !upcoming.fromUser;
    this.lastBusyAt = performance.now();
    const { line } = upcoming;
    if (line.stages.ready) {
      const seconds = (line.stages.ready - line.requestedAt) / 1000 + PREPARE_MARGIN_SECONDS;
      this.prepareSeconds += ESTIMATE_WEIGHT * (seconds - this.prepareSeconds);
    }
    start(line);
    this.onTurn?.(line.info.reason as TurnReason, line.info.frame, line.info.said);
  }

  /** A prepared line that failed or had nothing to say just gets dropped. */
  private dropIfUnusable() {
    const line = this.upcoming?.line;
    if (line && (line.failed || line.empty)) {
      if (line.failed) this.onProblem?.(line.error);
      if (line.declined) {
        this.declinedCount += 1;
        this.lastSeen = line.seen;
      }
      this.upcoming = null;
      this.backoffUntil = performance.now() + (line.declined ? DECLINED_BACKOFF_MS : FAILURE_BACKOFF_MS);
    }
  }

  private dropUpcoming() {
    if (this.upcoming) this.speech.cancel(this.upcoming.line);
    this.upcoming = null;
  }

  /** Remembers only the sentences that were heard. */
  private commit(line: PreparedLine) {
    if (!line.turnId) return;
    void fetch(COMMIT_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ turn_id: line.turnId, spoken: line.heard }),
    }).catch((err) => console.warn('could not save what she said:', err));
  }

  private rollJitter() {
    this.jitter = JITTER_MIN + Math.random() * (JITTER_MAX - JITTER_MIN);
  }
}
