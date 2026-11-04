import { clamp, damp, rand } from './math';

export type Vowel = 'A' | 'I' | 'U' | 'E' | 'O';
export const VOWELS: Vowel[] = ['A', 'I', 'U', 'E', 'O'];

interface Syllable {
  start: number;
  duration: number;
  open: number;
  vowel: Vowel;
}

const VOWEL_OF: Record<string, Vowel> = { a: 'A', i: 'I', y: 'I', u: 'U', w: 'U', e: 'E', o: 'O' };

/** Turns text into a timed syllable track: vowel groups for Latin text, one per CJK char. */
function textToSyllables(text: string, rate: number): Syllable[] {
  const out: Syllable[] = [];
  let t = 0.05;
  const tokens = text.toLowerCase().match(/[぀-ヿ㐀-鿿가-힯]|[a-z']+|[0-9]+|[.,!?;:…。，！？、]/g) ?? [];
  for (const tok of tokens) {
    if (/^[.!?…。！？]$/.test(tok)) {
      t += 0.42 / rate;
      continue;
    }
    if (/^[,;:，、]$/.test(tok)) {
      t += 0.22 / rate;
      continue;
    }
    if (/[぀-鿿가-힯]/.test(tok)) {
      const vowel = VOWELS[tok.charCodeAt(0) % 5];
      const duration = rand(0.13, 0.19) / rate;
      out.push({ start: t, duration, open: rand(0.55, 1), vowel });
      t += duration;
      continue;
    }
    const groups = tok.match(/[aeiouy]+/g) ?? [tok.length > 0 ? 'a' : ''];
    for (const g of groups) {
      const duration = rand(0.1, 0.17) / rate;
      out.push({ start: t, duration, open: rand(0.5, 1), vowel: VOWEL_OF[g[0]] ?? 'A' });
      t += duration;
    }
    t += 0.04 / rate; // tiny gap between words
  }
  return out;
}

/**
 * Drives the mouth. Three sources: babble from text (optionally voiced by the browser's
 * speech synthesis), or live audio (microphone / audio element) analysed for loudness and a
 * rough brightness-based vowel guess.
 */
export class Talker {
  open = 0;
  vowels: Record<Vowel, number> = { A: 0, I: 0, U: 0, E: 0, O: 0 };
  /** Smoothed speaking intensity, used for head bobs and eyebrow lifts. */
  energy = 0;
  /** 1 while the voice is sounding, easing to 0 in pauses; lets speech override posed mouths. */
  voiced = 0;
  /** Precomputed mouth track (SpeechPlayer); takes priority over the other sources while active. */
  source?: () => { open: number; vowel: Vowel | null } | null;
  private sourceActive = false;

  private track: Syllable[] = [];
  private trackTime = 0;
  private trackEnd = 0;
  private speechActive = false;
  private analyser: AnalyserNode | null = null;
  private audioCtx: AudioContext | null = null;
  private stopAudio: (() => void) | null = null;
  private floor = 0.01;
  private peak = 0.08;
  private timeBuf = new Float32Array(1024);
  private freqBuf = new Uint8Array(512);

  get speaking() {
    return this.sourceActive || this.trackTime < this.trackEnd || this.speechActive || this.analyser !== null;
  }

  /** Lip-flap animation for `text` without sound. */
  babble(text: string, rate = 1) {
    this.track = textToSyllables(text, rate);
    this.trackTime = 0;
    const last = this.track[this.track.length - 1];
    this.trackEnd = last ? last.start + last.duration : 0;
  }

  /** Speaks with the browser's built-in TTS and animates the mouth along with it. */
  speak(text: string, opts: { rate?: number; pitch?: number; voice?: SpeechSynthesisVoice | null } = {}) {
    const synth = window.speechSynthesis;
    if (!synth) return this.babble(text, opts.rate ?? 1);
    synth.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.rate = opts.rate ?? 1.05;
    u.pitch = opts.pitch ?? 1.5;
    if (opts.voice) u.voice = opts.voice;
    // TTS gives no amplitude, so babble a syllable track per spoken word as boundaries arrive;
    // if the voice never fires boundary events, fall back to babbling the whole text.
    let gotBoundary = false;
    u.onboundary = (e) => {
      if (e.name && e.name !== 'word') return;
      gotBoundary = true;
      const word = text.slice(e.charIndex, e.charIndex + (e.charLength || text.slice(e.charIndex).search(/\s|$/)));
      this.babble(word, u.rate);
    };
    u.onstart = () => {
      this.speechActive = true;
      setTimeout(() => {
        if (!gotBoundary && this.speechActive) this.babble(text, u.rate * 0.95);
      }, 350);
    };
    u.onend = u.onerror = () => {
      this.speechActive = false;
    };
    synth.speak(u);
  }

  stop() {
    this.track = [];
    this.trackEnd = 0;
    this.speechActive = false;
    window.speechSynthesis?.cancel();
    this.stopAudio?.();
  }

  async useMicrophone() {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const ctx = this.ensureCtx();
    const src = ctx.createMediaStreamSource(stream);
    this.attach(src, () => stream.getTracks().forEach((t) => t.stop()));
  }

  /** Plays an audio file/URL and lip-syncs to it. */
  async playAudio(url: string) {
    const ctx = this.ensureCtx();
    const el = new Audio(url);
    el.crossOrigin = 'anonymous';
    const src = ctx.createMediaElementSource(el);
    src.connect(ctx.destination);
    this.attach(src, () => el.pause());
    el.onended = () => this.stopAudio?.();
    await el.play();
  }

  private ensureCtx() {
    this.stopAudio?.();
    this.audioCtx ??= new AudioContext();
    void this.audioCtx.resume();
    return this.audioCtx;
  }

  private attach(src: AudioNode, cleanup: () => void) {
    const analyser = this.audioCtx!.createAnalyser();
    analyser.fftSize = 1024;
    analyser.smoothingTimeConstant = 0.3;
    src.connect(analyser);
    this.analyser = analyser;
    this.floor = 0.01;
    this.peak = 0.08;
    this.stopAudio = () => {
      src.disconnect();
      cleanup();
      this.analyser = null;
      this.stopAudio = null;
    };
  }

  update(dt: number) {
    let targetOpen = 0;
    const target: Record<Vowel, number> = { A: 0, I: 0, U: 0, E: 0, O: 0 };
    const external = this.source?.() ?? null;
    this.sourceActive = external !== null;

    if (external) {
      targetOpen = external.open;
      if (external.vowel) target[external.vowel] = 1;
    } else if (this.analyser) {
      this.analyser.getFloatTimeDomainData(this.timeBuf);
      let sum = 0;
      for (const s of this.timeBuf) sum += s * s;
      const rms = Math.sqrt(sum / this.timeBuf.length);
      // Adaptive noise floor and peak so it works for quiet mics and loud files alike.
      this.floor = rms < this.floor ? damp(this.floor, rms, 0.05, dt) : damp(this.floor, rms, 4, dt);
      this.peak = Math.max(rms, damp(this.peak, 0.04, 6, dt));
      const level = clamp((rms - this.floor * 1.5) / Math.max(0.02, this.peak - this.floor), 0, 1);
      targetOpen = Math.pow(level, 0.7);
      if (targetOpen > 0.05) {
        this.analyser.getByteFrequencyData(this.freqBuf);
        let num = 0;
        let den = 0;
        for (let i = 2; i < 120; i++) {
          num += i * this.freqBuf[i];
          den += this.freqBuf[i];
        }
        const centroid = den > 0 ? num / den : 30;
        // Very rough: dark sounds read as O/U, bright as I/E.
        const v: Vowel = centroid < 18 ? 'O' : centroid < 24 ? 'U' : centroid < 34 ? 'A' : centroid < 44 ? 'E' : 'I';
        target[v] = 1;
      }
    } else if (this.trackTime < this.trackEnd) {
      this.trackTime += dt;
      const t = this.trackTime;
      const syl = this.track.find((s) => t >= s.start && t < s.start + s.duration);
      if (syl) {
        const u = (t - syl.start) / syl.duration;
        // Open quickly, close a bit slower; never fully shut mid-word.
        const env = u < 0.35 ? u / 0.35 : 1 - ((u - 0.35) / 0.65) * 0.75;
        targetOpen = syl.open * env;
        target[syl.vowel] = 1;
      }
    } else if (this.speechActive) {
      // Voice still talking but the word track ran out: keep a gentle filler flap.
      const t = performance.now() / 1000;
      targetOpen = 0.35 + 0.3 * Math.sin(t * 17) * Math.sin(t * 5.3);
      target.A = 1;
    }

    this.open = damp(this.open, targetOpen, targetOpen > this.open ? 0.02 : 0.045, dt);
    for (const v of VOWELS) this.vowels[v] = damp(this.vowels[v], target[v], 0.05, dt);
    this.energy = damp(this.energy, this.speaking ? Math.max(this.open, 0.3) : 0, 0.25, dt);
    this.voiced = damp(this.voiced, targetOpen > 0.03 ? 1 : 0, targetOpen > 0.03 ? 0.02 : 0.2, dt);
  }
}
