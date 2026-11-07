import type { Animator } from './animator';
import type { Vowel } from './talk';

export interface SpeechCue {
  start: number;
  end: number;
  emotion: string;
  emoji: string;
  kind: 'trailing' | 'leading';
  arms: boolean;
}

export interface SpeechSegment {
  type: 'segment';
  index: number;
  /** Null for companion turns: the reply is still being written, so the total isn't known. */
  count: number | null;
  text: string;
  audio_base64: string;
  duration: number;
  fps: number;
  open: number[];
  vowel: string;
  cues: SpeechCue[];
  ignored_emoji: string[];
  alignment_score: number;
}

/** Server-side latency of one companion turn, in seconds from when the bridge received it. */
export interface TurnTrace {
  type: 'trace';
  kind: string;
  first_token?: number;
  expression?: number;
  first_sentence?: number;
  first_audio_ready?: number;
  total?: number;
  model?: string;
  provider?: string;
  cost?: number | null;
}

/** Why a line was made: shown in the panel, and never sent anywhere. */
export interface LineInfo {
  reason: string;
  frame: string | null;
  said: string | null;
}

interface Scheduled {
  line: PreparedLine;
  segment: SpeechSegment;
  startAt: number;
  endAt: number;
  nextCue: number;
  source: AudioBufferSourceNode;
  heard: boolean;
}

/** One reply: generated in the background, and only heard if it gets played. */
export class PreparedLine {
  turnId: string | null = null;
  receiving = true;
  failed = false;
  error = '';
  playing = false;
  /** Set once it can't make any more sound. */
  finished = false;
  expression: { emotion: string; emoji: string } | null = null;
  /** What she noted on screen before deciding whether to speak. */
  seen: string | null = null;
  /** She looked and chose to stay quiet. */
  declined = false;
  /** The kind of line the bridge asked for, such as a question or a reaction. */
  act: string | null = null;
  /** Ready to play, but not scheduled yet. */
  decoded: { segment: SpeechSegment; buffer: AudioBuffer }[] = [];
  scheduled: Scheduled[] = [];
  /** Everything written so far, whether heard or not. */
  written: string[] = [];
  /** The sentences that have started playing. */
  heard: string[] = [];
  /** performance.now() when each stage was reached. */
  stages: { writing?: number; tts?: number; ready?: number; speaking?: number } = {};
  readonly requestedAt = performance.now();
  readonly abort = new AbortController();
  gain: GainNode | null = null;
  settled: Promise<void> = Promise.resolve();

  constructor(readonly info: LineInfo) {}

  /** True once there's audio to play, or it has failed or come up empty. */
  get ready() {
    return this.decoded.length > 0 || this.scheduled.length > 0;
  }

  /** True if it ended with nothing to say. */
  get empty() {
    return !this.receiving && !this.ready;
  }
}

const VOWEL_OF: Record<string, Vowel> = { a: 'A', i: 'I', u: 'U', e: 'E', o: 'O' };
// The expression crossfade takes a moment, so cues fire this early to land on the words.
const CUE_LEAD_SECONDS = 0.15;
// Arm poses take longer to arrive than a face change.
const ARM_CUE_LEAD_SECONDS = 0.45;
// Breath between sentences of one reply.
const SEGMENT_GAP_SECONDS = 0.12;
// Pause when she changes course at the end of a sentence.
const SWITCH_GAP_SECONDS = 0.25;
const SCHEDULE_LEAD_SECONDS = 0.05;
// How long her voice takes to fade when you speak over her.
const FADE_SECONDS = 0.15;
// How long a reply's opening face holds before audio takes over with its own cues.
const EXPRESSION_HOLD_SECONDS = 6;

const decodeBase64 = (data: string) => Uint8Array.from(atob(data), (c) => c.charCodeAt(0)).buffer;

/**
 * Plays speech from the bridge, in sync with the audio clock. A line can be prepared in the
 * background while another plays, and sound never overlaps: the next one starts after the current
 * sentence. The lip track drives the mouth and expression cues fire at their aligned times.
 */
export class SpeechPlayer {
  onStatus?: (message: string, busy: boolean) => void;
  /** A sentence has started playing. */
  onSegment?: (segment: SpeechSegment, line: PreparedLine) => void;
  onCue?: (cue: SpeechCue, segmentTime: number) => void;
  onTrace?: (trace: TurnTrace) => void;
  /** Seconds since the line was requested. */
  onFace?: (emoji: string, seconds: number) => void;
  onFirstAudio?: (seconds: number) => void;
  /** A line that played is over, listing the sentences that were heard. */
  onLineDone?: (line: PreparedLine) => void;

  private ctx: AudioContext | null = null;
  private queue: Scheduled[] = [];
  private current: PreparedLine | null = null;
  private holdingFace = false;

  constructor(private readonly animator: Animator) {
    animator.talk.source = () => this.frame();
  }

  /** The line being played, or last played. */
  get line() {
    return this.current;
  }

  /** True while the line being played is still generating or making sound. */
  get active() {
    if (this.current?.receiving && !this.current.finished) return true;
    const now = this.ctx?.currentTime ?? 0;
    return this.queue.some((item) => item.endAt > now);
  }

  /** Seconds until she finishes, or null while more of the line may still arrive. */
  get secondsLeft() {
    if (this.current?.receiving && !this.current.finished) return null;
    return Math.max(0, this.lastEnd - (this.ctx?.currentTime ?? 0));
  }

  /** True if she can still change course at a sentence end before the line is over. */
  get hasLaterSentences() {
    const line = this.current;
    if (!line || line.finished) return false;
    if (line.receiving) return true;
    const now = this.ctx?.currentTime ?? 0;
    return line.decoded.length > 0 || line.scheduled.some((item) => item.startAt > now);
  }

  /** What she's in the middle of saying, for writing a line that follows it. */
  get saying() {
    return this.active && this.current ? this.current.written.join('') : '';
  }

  private get lastEnd() {
    return this.queue.length > 0 ? this.queue[this.queue.length - 1].endAt : 0;
  }

  /** Call from a click handler, or the browser blocks audio that starts later without one. */
  unlock() {
    this.ctx ??= new AudioContext();
    void this.ctx.resume();
  }

  /** Glances away for a moment, as if something caught her eye. */
  glance() {
    this.animator.gaze.glance();
  }

  /** Whether she's talking about what's on screen, so she looks at it. */
  watchScreen(on: boolean) {
    this.animator.gaze.watchingScreen = on;
  }

  speak(text: string) {
    return this.playStream('/speech/speak', { text });
  }

  /** Stops everything and plays a stream as it arrives. */
  async playStream(url: string, body: unknown) {
    this.stop();
    const line = this.prepare(url, body, { reason: '', frame: null, said: null });
    this.play(line);
    await line.settled;
  }

  /** Starts generating a line in the background. Nothing is heard until it's played. */
  prepare(url: string, body: unknown, info: LineInfo) {
    this.unlock();
    const line = new PreparedLine(info);
    line.settled = this.receive(line, url, body);
    return line;
  }

  /** Plays a line straight after whatever is playing. Later sentences follow as they arrive. */
  play(line: PreparedLine, gap = SEGMENT_GAP_SECONDS, notBefore = 0) {
    const ctx = this.ctx!;
    line.playing = true;
    this.current = line;
    line.gain = ctx.createGain();
    line.gain.connect(ctx.destination);
    this.onStatus?.('Speaking…', true);
    const waiting = line.decoded;
    line.decoded = [];
    waiting.forEach((item, index) => this.schedule(line, item.segment, item.buffer, index === 0 ? gap : SEGMENT_GAP_SECONDS, notBefore));
    if (waiting.length === 0) this.holdFace(line);
    if (line.stages.ready) this.onFirstAudio?.((line.stages.ready - line.requestedAt) / 1000);
    if (line.empty || line.failed) this.finish(line);
  }

  /** Changes course at the end of this sentence: later sentences of this line won't be heard. */
  switchTo(next: PreparedLine) {
    const now = this.ctx!.currentTime;
    const old = this.current;
    if (old) {
      old.abort.abort();
      old.receiving = false;
      old.decoded = [];
      for (const item of old.scheduled.filter((scheduled) => scheduled.startAt > now)) {
        item.source.stop();
        this.queue = this.queue.filter((queued) => queued !== item);
      }
      old.scheduled = old.scheduled.filter((item) => item.startAt <= now);
      this.finish(old);
    }
    this.play(next, SWITCH_GAP_SECONDS);
  }

  /** Fades her voice quickly and plays this line next, for when you speak to her. */
  fadeInto(next: PreparedLine) {
    const ctx = this.ctx!;
    const now = ctx.currentTime;
    const old = this.current;
    if (old) {
      old.abort.abort();
      old.receiving = false;
      old.decoded = [];
      old.gain?.gain.setValueAtTime(1, now);
      old.gain?.gain.linearRampToValueAtTime(0, now + FADE_SECONDS);
      for (const item of old.scheduled) item.source.stop(now + FADE_SECONDS);
      this.queue = this.queue.filter((item) => item.line !== old);
      old.scheduled = old.scheduled.filter((item) => item.startAt <= now);
      this.finish(old);
    }
    this.play(next, 0, now + FADE_SECONDS);
  }

  /** Drops a line that isn't playing. Nothing about it was heard. */
  cancel(line: PreparedLine) {
    line.abort.abort();
    line.receiving = false;
    line.finished = true;
    line.decoded = [];
  }

  /** Stops at once. */
  stop() {
    const line = this.current;
    if (line) {
      line.abort.abort();
      line.receiving = false;
      line.decoded = [];
      for (const item of line.scheduled) item.source.stop();
      line.scheduled = line.scheduled.filter((item) => item.startAt <= (this.ctx?.currentTime ?? 0));
    }
    if (this.queue.length > 0 || this.holdingFace) this.animator.endReaction();
    this.holdingFace = false;
    this.queue = [];
    if (line) this.finish(line);
    this.onStatus?.('', false);
  }

  /** Notices sentences starting and lines ending, from the audio clock, so it runs while she's hidden. */
  poll() {
    const now = this.ctx?.currentTime;
    if (now === undefined) return;
    for (const item of this.queue) {
      if (!item.heard && item.startAt <= now) {
        item.heard = true;
        item.line.heard.push(item.segment.text);
        item.line.stages.speaking ??= performance.now();
        this.holdingFace = false;
        this.onSegment?.(item.segment, item.line);
      }
    }
    const line = this.current;
    if (line && !line.finished && !line.receiving && line.decoded.length === 0 && line.scheduled.every((item) => item.endAt <= now)) {
      this.finish(line);
      if (!this.active) this.onStatus?.('', false);
    }
  }

  private finish(line: PreparedLine) {
    if (line.finished) return;
    this.pollHeard(line);
    line.finished = true;
    this.onLineDone?.(line);
  }

  /** Sentences that started before the line ended, in case nothing has polled since. */
  private pollHeard(line: PreparedLine) {
    const now = this.ctx?.currentTime ?? 0;
    for (const item of line.scheduled) {
      if (!item.heard && item.startAt <= now) {
        item.heard = true;
        line.heard.push(item.segment.text);
        this.onSegment?.(item.segment, line);
      }
    }
  }

  private holdFace(line: PreparedLine) {
    if (!line.expression) return;
    this.holdingFace = true;
    this.animator.react(line.expression.emotion, EXPRESSION_HOLD_SECONDS, { arms: false });
    this.onFace?.(line.expression.emoji, (performance.now() - line.requestedAt) / 1000);
  }

  private async receive(line: PreparedLine, url: string, body: unknown) {
    const { signal } = line.abort;
    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal,
      });
      if (!response.ok || !response.body) throw new Error(`speech bridge returned ${response.status}`);
      await this.readLines(line, response.body, signal);
    } catch (err) {
      if (signal.aborted) return;
      line.failed = true;
      line.error = err instanceof Error ? err.message : String(err);
      if (line.playing) {
        if (this.holdingFace) this.animator.endReaction();
        this.holdingFace = false;
        this.onStatus?.(`Speech failed: ${line.error}. Are the TTS server and bridge running?`, false);
      }
    } finally {
      line.receiving = false;
      if (line.playing && line.empty) this.finish(line);
    }
  }

  private async readLines(line: PreparedLine, body: ReadableStream<Uint8Array>, signal: AbortSignal) {
    const reader = body.getReader();
    const decoder = new TextDecoder();
    let pending = '';
    for (;;) {
      const { done, value } = await reader.read();
      if (done || signal.aborted) return;
      pending += decoder.decode(value, { stream: true });
      const lines = pending.split('\n');
      pending = lines.pop() ?? '';
      for (const raw of lines) {
        if (!raw.trim()) continue;
        const message = JSON.parse(raw);
        if (message.type === 'error') throw new Error(message.message);
        if (message.type === 'turn') {
          line.turnId = message.turn_id;
          line.act = message.act ?? null;
        }
        if (message.type === 'seen') line.seen = message.text;
        if (message.type === 'declined') line.declined = true;
        if (message.type === 'trace') this.onTrace?.(message as TurnTrace);
        if (message.type === 'stage') {
          if (message.stage === 'writing') line.stages.writing ??= performance.now();
          if (message.stage === 'tts') line.stages.tts ??= performance.now();
        }
        if (message.type === 'expression') {
          line.expression = { emotion: message.emotion, emoji: message.emoji };
          if (line.playing && !line.ready) this.holdFace(line);
        }
        if (message.type === 'segment') await this.receiveSegment(line, message as SpeechSegment, signal);
      }
    }
  }

  private async receiveSegment(line: PreparedLine, segment: SpeechSegment, signal: AbortSignal) {
    const buffer = await this.ctx!.decodeAudioData(decodeBase64(segment.audio_base64));
    if (signal.aborted) return;
    line.written.push(segment.text);
    if (!line.stages.ready) {
      line.stages.ready = performance.now();
      if (line.playing) this.onFirstAudio?.((line.stages.ready - line.requestedAt) / 1000);
    }
    if (line.playing) this.schedule(line, segment, buffer);
    else line.decoded.push({ segment, buffer });
  }

  private schedule(line: PreparedLine, segment: SpeechSegment, buffer: AudioBuffer, gap = SEGMENT_GAP_SECONDS, notBefore = 0) {
    const ctx = this.ctx!;
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(line.gain ?? ctx.destination);
    const lastEnd = this.lastEnd;
    const startAt = Math.max(ctx.currentTime + SCHEDULE_LEAD_SECONDS, lastEnd > 0 ? lastEnd + gap : 0, notBefore);
    source.start(startAt);
    const item: Scheduled = { line, segment, startAt, endAt: startAt + buffer.duration, nextCue: 0, source, heard: false };
    this.queue.push(item);
    line.scheduled.push(item);
    this.onStatus?.(segment.count === null ? 'Speaking…' : `Speaking… (part ${segment.index + 1}/${segment.count})`, true);
  }

  /** Called once per animation frame by the Talker: fires due cues, returns the current mouth. */
  private frame(): { open: number; vowel: Vowel | null } | null {
    this.poll();
    if (!this.ctx || this.queue.length === 0) return null;
    // outputLatency is how long audio takes to reach the speakers after it is scheduled.
    const now = this.ctx.currentTime - (this.ctx.outputLatency || 0);

    while (this.queue.length > 0 && now > this.queue[0].endAt) this.queue.shift();
    const item = this.queue[0];
    if (!item) return null;

    const t = now - item.startAt;
    const { segment } = item;
    while (item.nextCue < segment.cues.length) {
      const cue = segment.cues[item.nextCue];
      const lead = cue.arms ? ARM_CUE_LEAD_SECONDS : CUE_LEAD_SECONDS;
      if (t + lead < cue.start) break;
      item.nextCue += 1;
      if (t < cue.end) {
        this.animator.react(cue.emotion, cue.end - t, { arms: cue.arms });
        this.onCue?.(cue, t);
      }
    }

    if (t < 0) return { open: 0, vowel: null };
    const index = Math.floor(t * segment.fps);
    return {
      open: segment.open[index] ?? 0,
      vowel: VOWEL_OF[segment.vowel[index]] ?? null,
    };
  }
}
