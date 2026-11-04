/**
 * Minimal Cubism motion3.json evaluator. We play motions ourselves (instead of through the
 * library's motion manager) so they can be layered with procedural animation and hold their
 * last frame, which the rig's arm-pose transitions rely on.
 */

type Segment =
  | { kind: 'linear'; t0: number; v0: number; t1: number; v1: number }
  | { kind: 'bezier'; t0: number; v0: number; c1t: number; c1v: number; c2t: number; c2v: number; t1: number; v1: number }
  | { kind: 'stepped'; t0: number; v0: number; t1: number; v1: number }
  | { kind: 'inverse'; t0: number; v0: number; t1: number; v1: number };

interface Curve {
  id: string;
  segments: Segment[];
}

export interface Motion3Json {
  Meta: { Duration: number; Loop: boolean };
  Curves: { Target: string; Id: string; Segments: number[] }[];
}

function parseCurve(id: string, s: number[]): Curve {
  const segments: Segment[] = [];
  let t0 = s[0];
  let v0 = s[1];
  for (let i = 2; i < s.length; ) {
    const type = s[i++];
    if (type === 1) {
      const [c1t, c1v, c2t, c2v, t1, v1] = s.slice(i, i + 6);
      segments.push({ kind: 'bezier', t0, v0, c1t, c1v, c2t, c2v, t1, v1 });
      i += 6;
      t0 = t1;
      v0 = v1;
    } else {
      const [t1, v1] = s.slice(i, i + 2);
      const kind = type === 0 ? 'linear' : type === 2 ? 'stepped' : 'inverse';
      segments.push({ kind, t0, v0, t1, v1 });
      i += 2;
      t0 = t1;
      v0 = v1;
    }
  }
  if (segments.length === 0) segments.push({ kind: 'stepped', t0, v0, t1: t0, v1: v0 });
  return { id, segments };
}

const cubic = (a: number, b: number, c: number, d: number, u: number) => {
  const iu = 1 - u;
  return iu * iu * iu * a + 3 * iu * iu * u * b + 3 * iu * u * u * c + u * u * u * d;
};

function evalSegment(seg: Segment, t: number): number {
  const span = seg.t1 - seg.t0;
  switch (seg.kind) {
    case 'linear':
      return span <= 0 ? seg.v1 : seg.v0 + ((t - seg.t0) / span) * (seg.v1 - seg.v0);
    case 'stepped':
      return t >= seg.t1 ? seg.v1 : seg.v0;
    case 'inverse':
      return t > seg.t0 ? seg.v1 : seg.v0;
    case 'bezier': {
      // Solve the time polynomial for u by bisection, then evaluate the value polynomial.
      let lo = 0;
      let hi = 1;
      for (let k = 0; k < 20; k++) {
        const mid = (lo + hi) / 2;
        if (cubic(seg.t0, seg.c1t, seg.c2t, seg.t1, mid) < t) lo = mid;
        else hi = mid;
      }
      return cubic(seg.v0, seg.c1v, seg.c2v, seg.v1, (lo + hi) / 2);
    }
  }
}

export class Motion3 {
  readonly duration: number;
  private readonly curves: Curve[];

  constructor(json: Motion3Json, readonly loop = json.Meta.Loop) {
    this.duration = json.Meta.Duration;
    this.curves = json.Curves.filter((c) => c.Target === 'Parameter').map((c) => parseCurve(c.Id, c.Segments));
  }

  static async load(url: string, loop?: boolean) {
    const json = (await (await fetch(url)).json()) as Motion3Json;
    return new Motion3(json, loop);
  }

  get ids() {
    return this.curves.map((c) => c.id);
  }

  /** Calls `out(id, value)` for every curve at time `t` (wrapped if looping, else held). */
  evaluate(t: number, out: (id: string, value: number) => void) {
    const time = this.loop ? t % this.duration : Math.min(t, this.duration);
    for (const curve of this.curves) {
      const segs = curve.segments;
      let seg = segs[segs.length - 1];
      for (const s of segs) {
        if (time <= s.t1) {
          seg = s;
          break;
        }
      }
      out(curve.id, evalSegment(seg, Math.max(seg.t0, Math.min(seg.t1, time))));
    }
  }
}

/** Plays a non-looping motion once and keeps outputting its final frame. */
export class HeldMotionPlayer {
  private motion: Motion3 | null = null;
  private time = 0;

  play(motion: Motion3) {
    this.motion = motion;
    this.time = 0;
  }

  get playing() {
    return this.motion !== null && this.time < this.motion.duration;
  }

  update(dt: number, out: (id: string, value: number) => void) {
    if (!this.motion) return;
    this.time += dt;
    this.motion.evaluate(this.time, out);
  }
}
