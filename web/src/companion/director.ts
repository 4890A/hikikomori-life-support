import type { PreparedLine, SpeechPlayer } from '../anim/speech';
import { startClock } from './clock';
import type { ShareSource } from './desktopGaze';
import { BIG_CHANGE, CHATTINESS, nextAction, type Action, type Chattiness, type TurnReason } from './pacing';
import { ScreenWatcher } from './screen';

export { CHATTINESS, type Chattiness, type TurnReason };

const TURN_URL = '/speech/companion/turn';
const COMMIT_URL = '/speech/companion/commit';
const SESSION_END_URL = '/speech/companion/session/end';
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
const SHARE_WINDOW_MS = 90_000;
const SHARE_MIN_WINDOW_MS = 30_000;
// A question mark near the end of her line, allowing for a closing emoji.
const ASKS = /[？?][^？?]{0,4}$/u;

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
  // For pacing: when she was talking lately, her last line, and her lines since you last spoke.
  private talked: { at: number; ms: number }[] = [];
  private lastTick = performance.now();
  private startedAt = performance.now();
  private lastLineSeconds = 0;
  private unpromptedRun = 0;
  private askedYou = false;

  /** Share of the last 90 s she spent talking, from 0 to 1, for pacing and the panel. */
  get talkShare() {
    const now = performance.now();
    const spoken = this.talked.reduce((sum, item) => sum + item.ms, 0);
    // Early on, a short window would make one line look like a lot.
    return spoken / Math.max(SHARE_MIN_WINDOW_MS, Math.min(SHARE_WINDOW_MS, now - this.startedAt));
  }

  constructor(private readonly speech: SpeechPlayer) {
    speech.onLineDone = (line) => this.commit(line);
    // Closing the page ends the session too, so it becomes a memory.
    window.addEventListener('pagehide', () => {
      if (this.watcher) this.endSession();
    });
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
    this.startedAt = performance.now();
    this.talked = [];
    this.unpromptedRun = 0;
    this.askedYou = false;
    this.rollJitter();
    // She says hello first, mentioning last time if she remembers it.
    if (!this.upcoming) this.prepare('greeting', false, 0);
  }

  stop() {
    if (!this.watcher) return;
    this.watcher.stop();
    this.watcher = null;
    this.dropUpcoming();
    // Stopping her voice commits what was heard, which should land in this session before it ends.
    this.speech.stop();
    this.endSession();
    this.speech.watchScreen(false);
    this.onShare?.(null);
    this.onStopped?.();
  }

  /** Your words come first: her reply starts as soon as it's ready, and her voice fades into it. */
  say(text: string) {
    this.dropUpcoming();
    this.unpromptedRun = 0;
    this.askedYou = false;
    // The screen as you spoke, so she can answer 「これ何？」 ("What's this?").
    const image = this.watcher?.frame();
    const line = this.speech.prepare(TURN_URL, { kind: 'speech', text, image }, { reason: 'you spoke', frame: image ?? null, said: text });
    this.upcoming = { line, urgent: true, fromUser: true, pause: 0 };
    this.update();
  }

  private update() {
    this.speech.poll();
    const now = performance.now();
    const elapsed = Math.min(now - this.lastTick, 250);
    this.lastTick = now;
    if (!this.watcher && !this.upcoming) return;
    const speaking = this.speech.active;
    if (speaking) this.talked.push({ at: now, ms: elapsed });
    while (this.talked.length > 0 && this.talked[0].at < now - SHARE_WINDOW_MS) this.talked.shift();
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
        talkShare: this.talkShare,
        lastLineSeconds: this.lastLineSeconds,
        unpromptedRun: this.unpromptedRun,
        askedYou: this.askedYou,
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
    this.unpromptedRun = upcoming.fromUser ? 0 : this.unpromptedRun + 1;
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
    // How long it lasted and whether it asked you something set the pause after it.
    if (line.stages.speaking) this.lastLineSeconds = (performance.now() - line.stages.speaking) / 1000;
    if (line.heard.length > 0) this.askedYou = ASKS.test(line.heard.join(''));
    if (!line.turnId) return;
    void fetch(COMMIT_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ turn_id: line.turnId, spoken: line.heard }),
    }).catch((err) => console.warn('could not save what she said:', err));
  }

  /** Lets the bridge turn this session into a memory. A beacon still gets through as the page closes. */
  private endSession() {
    navigator.sendBeacon(SESSION_END_URL);
  }

  private rollJitter() {
    this.jitter = JITTER_MIN + Math.random() * (JITTER_MAX - JITTER_MIN);
  }
}
