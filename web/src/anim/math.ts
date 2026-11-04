export const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
export const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
export const smoothstep = (t: number) => {
  const x = clamp(t, 0, 1);
  return x * x * (3 - 2 * x);
};
export const rand = (lo: number, hi: number) => lo + Math.random() * (hi - lo);

/** Frame-rate independent exponential approach; `halfLife` in seconds. */
export const damp = (current: number, target: number, halfLife: number, dt: number) =>
  halfLife <= 0 ? target : lerp(target, current, Math.pow(2, -dt / halfLife));

/** Critically damped spring, gives a natural ease-in/ease-out follow with slight lag. */
export class Spring {
  value: number;
  velocity = 0;
  constructor(value = 0, public frequency = 3) {
    this.value = value;
  }
  update(target: number, dt: number) {
    const w = 2 * Math.PI * this.frequency;
    const x = this.value - target;
    const exp = Math.exp(-w * dt);
    const v = this.velocity;
    this.value = target + (x + (v + w * x) * dt) * exp;
    this.velocity = (v - w * (v + w * x) * dt) * exp;
    return this.value;
  }
}

/** Smooth 1D value noise in [-1, 1]; cheap way to get organic idle drift. */
export class Noise1D {
  private readonly table: Float32Array;
  constructor(seed = Math.random() * 1e9) {
    this.table = new Float32Array(256);
    let s = seed >>> 0 || 1;
    for (let i = 0; i < 256; i++) {
      s = (s * 1664525 + 1013904223) >>> 0;
      this.table[i] = (s / 0xffffffff) * 2 - 1;
    }
  }
  sample(t: number) {
    const i = Math.floor(t);
    const f = t - i;
    const a = this.table[i & 255];
    const b = this.table[(i + 1) & 255];
    return lerp(a, b, f * f * (3 - 2 * f));
  }
  /** Two octaves for a less regular look. */
  fbm(t: number) {
    return (this.sample(t) * 0.7 + this.sample(t * 2.3 + 17) * 0.3) / 1.0;
  }
}
