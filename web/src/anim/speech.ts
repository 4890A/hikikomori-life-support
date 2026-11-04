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

interface Scheduled {
  segment: SpeechSegment;
  startAt: number;
  endAt: number;
  nextCue: number;
  source: AudioBufferSourceNode;
}

const VOWEL_OF: Record<string, Vowel> = { a: 'A', i: 'I', u: 'U', e: 'E', o: 'O' };
// The expression crossfade takes a moment, so cues fire this early to land on the words.
const CUE_LEAD_SECONDS = 0.15;
// Arm poses take longer to arrive than a face change.
const ARM_CUE_LEAD_SECONDS = 0.45;
// Breath between separately synthesized segments.
const SEGMENT_GAP_SECONDS = 0.12;
// How long a reply's opening face holds before audio takes over with its own cues.
const EXPRESSION_HOLD_SECONDS = 6;

const decodeBase64 = (data: string) => Uint8Array.from(atob(data), (c) => c.charCodeAt(0)).buffer;

/**
 * Plays speech from the bridge, in sync with the audio clock: segments are queued gaplessly as
 * they arrive, the lip track drives the mouth and expression cues fire at their aligned times.
 */
export class SpeechPlayer {
  onStatus?: (message: string, busy: boolean) => void;
  onSegment?: (segment: SpeechSegment) => void;
  onCue?: (cue: SpeechCue, segmentTime: number) => void;
  onTrace?: (trace: TurnTrace) => void;
  /** Seconds since the request was sent, as seen in the browser. */
  onFace?: (emoji: string, seconds: number) => void;
  onFirstAudio?: (seconds: number) => void;

  private ctx: AudioContext | null = null;
  private queue: Scheduled[] = [];
  private abort: AbortController | null = null;
  private receiving = false;
  private requestedAt = 0;
  private audioScheduled = false;
  private holdingFace = false;

  constructor(private readonly animator: Animator) {
    animator.talk.source = () => this.frame();
  }

  /** True while generating or playing. Uses the audio clock, because frames stop when she's hidden. */
  get active() {
    if (this.receiving) return true;
    const now = this.ctx?.currentTime ?? 0;
    return this.queue.some((item) => item.endAt > now);
  }

  /** Call from a click handler, or the browser blocks audio that starts later without one. */
  unlock() {
    this.ctx ??= new AudioContext();
    void this.ctx.resume();
  }

  speak(text: string) {
    return this.playStream('/speech/speak', { text });
  }

  /** Plays a stream of expression, segment and trace lines from the bridge. */
  async playStream(url: string, body: unknown) {
    this.stop();
    this.unlock();
    this.requestedAt = performance.now();
    this.audioScheduled = false;
    const abort = new AbortController();
    this.abort = abort;
    this.receiving = true;
    this.onStatus?.('Generating speech…', true);
    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: abort.signal,
      });
      if (!response.ok || !response.body) throw new Error(`speech bridge returned ${response.status}`);
      await this.readLines(response.body, abort.signal);
      if (!abort.signal.aborted) this.onStatus?.('Speaking…', true);
    } catch (err) {
      if (abort.signal.aborted) return;
      this.releaseFace();
      this.onStatus?.(`Speech failed: ${err instanceof Error ? err.message : err}. Are the TTS server and bridge running?`, false);
    } finally {
      if (this.abort === abort) this.receiving = false;
    }
  }

  stop() {
    this.abort?.abort();
    this.abort = null;
    this.receiving = false;
    for (const item of this.queue) {
      item.source.onended = null;
      item.source.stop();
    }
    if (this.queue.length > 0) this.animator.endReaction();
    else this.releaseFace();
    this.holdingFace = false;
    this.queue = [];
    this.onStatus?.('', false);
  }

  private releaseFace() {
    if (this.holdingFace) this.animator.endReaction();
    this.holdingFace = false;
  }

  private async readLines(body: ReadableStream<Uint8Array>, signal: AbortSignal) {
    const reader = body.getReader();
    const decoder = new TextDecoder();
    let pending = '';
    for (;;) {
      const { done, value } = await reader.read();
      if (done || signal.aborted) return;
      pending += decoder.decode(value, { stream: true });
      const lines = pending.split('\n');
      pending = lines.pop() ?? '';
      for (const line of lines) {
        if (!line.trim()) continue;
        const message = JSON.parse(line);
        if (message.type === 'error') throw new Error(message.message);
        if (message.type === 'segment') await this.enqueue(message as SpeechSegment, signal);
        if (message.type === 'trace') this.onTrace?.(message as TurnTrace);
        if (message.type === 'expression') {
          this.holdingFace = true;
          this.animator.react(message.emotion, EXPRESSION_HOLD_SECONDS, { arms: false });
          this.onFace?.(message.emoji, (performance.now() - this.requestedAt) / 1000);
        }
      }
    }
  }

  private async enqueue(segment: SpeechSegment, signal: AbortSignal) {
    const ctx = this.ctx!;
    const buffer = await ctx.decodeAudioData(decodeBase64(segment.audio_base64));
    if (signal.aborted) return;
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(ctx.destination);
    const last = this.queue[this.queue.length - 1];
    const startAt = Math.max(ctx.currentTime + 0.05, last ? last.endAt + SEGMENT_GAP_SECONDS : 0);
    source.start(startAt);
    this.holdingFace = false;
    if (!this.audioScheduled) {
      this.audioScheduled = true;
      this.onFirstAudio?.((performance.now() - this.requestedAt) / 1000 + (startAt - ctx.currentTime));
    }
    this.queue.push({ segment, startAt, endAt: startAt + buffer.duration, nextCue: 0, source });
    this.onStatus?.(segment.count === null ? 'Speaking…' : `Speaking… (part ${segment.index + 1}/${segment.count})`, true);
    this.onSegment?.(segment);
  }

  /** Called once per animation frame by the Talker: fires due cues, returns the current mouth. */
  private frame(): { open: number; vowel: Vowel | null } | null {
    if (!this.ctx || this.queue.length === 0) return null;
    // outputLatency is how long audio takes to reach the speakers after it is scheduled.
    const now = this.ctx.currentTime - (this.ctx.outputLatency || 0);

    while (this.queue.length > 0 && now > this.queue[0].endAt) {
      this.queue.shift();
      if (this.queue.length === 0 && !this.receiving) this.onStatus?.('', false);
    }
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
