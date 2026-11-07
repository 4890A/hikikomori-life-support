import type { Params } from '../live2d';
import { Blinker } from './blink';
import { EMOTIONS, type Emotion, type EmotionWriter, type GazeBias } from './emotions';
import { Gaze } from './gaze';
import { Inertia } from './inertia';
import { clamp, damp, lerp, Noise1D, rand, smoothstep } from './math';
import { HeldMotionPlayer, Motion3 } from './motion3';
import { Talker, VOWELS } from './talk';

const MOTION_DIR = '/model/deepseek/motions/';
// Our own authored motions (see src/live2dselfrigging/motions.py).
const ACTION_DIR = '/motions/';
export const ACTIONS = { six_seven: '6 7' } as const;
export type ActionName = keyof typeof ACTIONS;
// The bundled arm motions also key the tail "light" params; leave those to the idle loop.
const ARM_MOTION_SKIP = new Set(['Param55', 'Param56', 'Param57', 'Param58']);
// Posed-arm parameters. Actions own these outright; everything else they key is additive.
const ARM_PARAMS = new Set([
  'Movement1', 'Movement2', 'Movement3', 'Param36', 'Param39', 'Param40', 'Param41', 'Param42', 'Param43',
  'Param59', 'Param60', 'Param61', 'Param62',
]);
// Default (hanging) arm joints. Physics writes these for sway, so actions set them after physics.
const PHYSICS_ARM_PARAMS = new Set([
  'LArm', 'LForearm', 'LWrist', 'LHand', 'LHand2', 'RArm', 'RForearm', 'RWrist', 'RHand', 'RHand2', 'Param44', 'Param25',
]);

interface EmotionState {
  def: Emotion;
  weight: number;
  time: number;
}

/** One arm's held pose, sequencing "put away" before "bring out" when switching poses. */
class ArmChannel {
  pose: string | null = null;
  private readonly player = new HeldMotionPlayer();
  private queued: Motion3 | null = null;

  constructor(private readonly motions: Record<string, { on: Motion3; off: Motion3 }>) {}

  request(pose: string | null) {
    if (pose === this.pose) return;
    const prev = this.pose;
    this.pose = pose;
    const next = pose ? this.motions[pose].on : null;
    if (prev) {
      this.player.play(this.motions[prev].off);
      this.queued = next;
    } else if (next) {
      this.player.play(next);
    }
  }

  update(dt: number, out: (id: string, v: number) => void) {
    if (this.queued && !this.player.playing) {
      this.player.play(this.queued);
      this.queued = null;
    }
    this.player.update(dt, out);
  }
}

/** Small idle "life" actions while nothing else is going on. */
class Fidgets {
  private next = rand(6, 10);
  private active: { kind: number; t: number; len: number; sign: number } | null = null;
  private time = 0;

  update(dt: number, allowed: boolean, out: EmotionWriter) {
    this.time += dt;
    if (!this.active) {
      if (allowed && this.time > this.next) {
        this.active = { kind: Math.floor(Math.random() * 4), t: 0, len: rand(1.8, 3), sign: Math.random() < 0.5 ? -1 : 1 };
      }
      return;
    }
    const a = this.active;
    a.t += dt;
    const env = Math.sin(Math.PI * clamp(a.t / a.len, 0, 1)); // ease in and out
    switch (a.kind) {
      case 0: // curious head tilt
        out.add('AngleZ', 11 * a.sign * env);
        out.add('ParamBrowLY', 0.3 * env);
        break;
      case 1: // ear flick (the ears follow the brows through physics)
        out.add('ParamBrowLY', 0.9 * Math.sin(a.t * 18) * env);
        out.add('ParamBrowRY', 0.9 * Math.sin(a.t * 18 + 0.8) * env);
        break;
      case 2: // content little hum
        out.add('ParamMouthForm', 0.8 * env);
        out.add('EyeSmile', 0.7 * env);
        out.add('AngleZ', 5 * Math.sin(a.t * 3) * env);
        break;
      case 3: // lean in to peer at the viewer
        out.add('LeanInput', -14 * env);
        out.add('ParamEyeLOpen', 0.15 * env);
        out.add('ParamEyeROpen', 0.15 * env);
        break;
    }
    if (a.t >= a.len) {
      this.active = null;
      this.time = 0;
      this.next = rand(7, 16);
    }
  }
}

export interface AnimatorOptions {
  idle: boolean;
  blink: boolean;
  followPointer: boolean;
}

/**
 * Composes every animation layer into parameter values each frame, right before physics.
 * Order: idle FX loop → emotion poses (crossfaded) + procedural motion → idle drift/fidgets →
 * gaze → talking → blinking (multiplies eye openness) → arm pose motions (absolute).
 */
export class Animator {
  readonly gaze = new Gaze();
  /** Her body trailing her window when it's dragged. Set its anchor from the window's position. */
  readonly inertia = new Inertia();
  /**
   * How strongly that lag moves her, per CSS pixel, and the most it can. These parameters are the
   * rig's physics inputs, so her hair and clothes swing with them as the rigger set up. (Cubism's
   * wind would push the whole rig, body included, and makes some parts jump.)
   */
  readonly sway = { position: 0.1, tilt: 0.17, headTilt: 0.08, maxPosition: 15, maxTilt: 15 };
  readonly blink = new Blinker();
  readonly talk = new Talker();
  readonly options: AnimatorOptions = { idle: true, blink: true, followPointer: true };
  /** Absolute parameter values that stay applied (outfit / accessory toggles). */
  readonly toggles: Record<string, number> = { Clothes1: 0 };

  private emotion = 'neutral';
  private previous = 'neutral';
  private reactionEnd = Infinity;
  private readonly states = new Map<string, EmotionState>();
  private readonly acc = new Map<string, number>();
  private readonly base = new Map<string, number>();
  private readonly noise = Array.from({ length: 6 }, (_, i) => new Noise1D(i * 7919 + 13));
  private readonly fidgets = new Fidgets();
  private time = 0;
  private rightArm!: ArmChannel;
  private leftArm!: ArmChannel;
  private idleFx!: Motion3;
  private actions!: Record<ActionName, { motion: Motion3; mirror?: Motion3 }>;
  private action: { motion: Motion3; mirror?: Motion3; time: number } | null = null;
  /** Arm values for the mirrored right open hand (see MirrorArm), while an action needs it. */
  readonly mirrorArm = new Map<string, number>();
  private actionWeight = 0;
  private readonly actionArms = new Map<string, number>();
  private readonly actionPostPhysics = new Map<string, number>();

  onEmotionChange?: (name: string) => void;

  private constructor(private readonly params: Params) {}

  static async create(params: Params) {
    const a = new Animator(params);
    const load = (name: string) => Motion3.load(`${MOTION_DIR}${name}.motion3.json`, false);
    const [idleFx, fingerOn, fingerOff, grassOn, grassOff, chestOn, chestOff, sixSeven, sixSevenMirror] = await Promise.all([
      Motion3.load(`${MOTION_DIR}idle_fx.motion3.json`, true),
      load('finger_up'),
      load('finger_down'),
      load('grass_on'),
      load('grass_off'),
      load('hand_chest_on'),
      load('hand_chest_off'),
      Motion3.load(`${ACTION_DIR}six_seven.motion3.json`, false),
      Motion3.load(`${ACTION_DIR}six_seven.mirror.motion3.json`, false),
    ]);
    a.idleFx = idleFx;
    a.actions = { six_seven: { motion: sixSeven, mirror: sixSevenMirror } };
    a.rightArm = new ArmChannel({ finger: { on: fingerOn, off: fingerOff }, grass: { on: grassOn, off: grassOff } });
    a.leftArm = new ArmChannel({ chest: { on: chestOn, off: chestOff } });
    a.states.set('neutral', { def: EMOTIONS.neutral, weight: 1, time: 0 });
    return a;
  }

  get currentEmotion() {
    return this.emotion;
  }

  /** Switches emotion; one-shot emotions (with `duration`) return to the previous one. */
  setEmotion(name: string) {
    this.react(name, EMOTIONS[name]?.duration ?? Infinity);
  }

  /** Shows `name` for `seconds`, then returns to whatever was showing before. */
  react(name: string, seconds: number, { arms = true }: { arms?: boolean } = {}) {
    const def = EMOTIONS[name];
    if (!def) throw new Error(`unknown emotion ${name}`);
    if (name !== this.emotion && this.reactionEnd === Infinity) this.previous = this.emotion;
    this.reactionEnd = this.time + seconds;
    this.emotion = name;
    const state = this.states.get(name);
    if (state) state.time = state.weight > 0.05 ? state.time : 0;
    else this.states.set(name, { def, weight: 0, time: 0 });
    this.rightArm.request(arms ? (def.rightArm ?? null) : null);
    this.leftArm.request(arms ? (def.leftArm ?? null) : null);
    this.onEmotionChange?.(name);
  }

  /** Ends a timed reaction early, returning to the emotion from before it. */
  endReaction() {
    if (this.reactionEnd !== Infinity) this.setEmotion(this.previous);
  }

  /** Plays a one-shot gesture over whatever emotion is showing. */
  playAction(name: ActionName) {
    this.action = { ...this.actions[name], time: 0 };
    // Put away any held arm pose; it is brought back when the action ends.
    this.rightArm.request(null);
    this.leftArm.request(null);
  }

  get actionPlaying() {
    return this.action !== null;
  }

  /** True while the playing action draws her right hand with the mirrored open-hand arm. */
  get mirrorActive() {
    return this.action?.mirror !== undefined;
  }

  // --- accumulation helpers -------------------------------------------------------------

  private baseOf(id: string) {
    return this.base.get(id) ?? this.params.defaultOf(id);
  }

  private add(id: string, v: number) {
    this.acc.set(id, (this.acc.get(id) ?? 0) + v);
  }

  private value(id: string) {
    return this.baseOf(id) + (this.acc.get(id) ?? 0);
  }

  update(dt: number) {
    this.time += dt;
    this.acc.clear();
    this.base.clear();
    const t = this.time;

    // 1. Rigger's idle effect loop (twinkles, tear/sweat flows when those keys are on).
    this.idleFx.evaluate(t, (id, v) => this.base.set(id, v));
    for (const [id, v] of Object.entries(this.toggles)) this.base.set(id, v);

    // 2. Emotions: crossfade weights, pose targets and procedural layers.
    if (t > this.reactionEnd) this.setEmotion(this.previous);
    let gazeBias: GazeBias = { x: 0, y: 0, weight: 0 };
    let blinkInterval: [number, number] = [2.2, 5.5];
    let blinkWeight = 0;
    let noBlink = 0;
    for (const [name, s] of this.states) {
      const target = name === this.emotion ? 1 : 0;
      s.weight = damp(s.weight, target, target ? 0.12 : 0.18, dt);
      s.time += dt;
      if (s.weight < 0.002 && !target) {
        this.states.delete(name);
        continue;
      }
      const w = smoothstep(s.weight);
      for (const [id, v] of Object.entries(s.def.pose)) this.add(id, w * (v - this.baseOf(id)));
      s.def.animate?.(s.time, {
        add: (id, v) => this.add(id, w * v),
        set: (id, v) => this.add(id, w * (v - this.value(id))),
      });
      if (s.def.gaze) {
        const g = typeof s.def.gaze === 'function' ? s.def.gaze(s.time) : s.def.gaze;
        gazeBias = { x: gazeBias.x + g.x * w, y: gazeBias.y + g.y * w, weight: gazeBias.weight + g.weight * w };
      }
      if (s.def.blink === false) noBlink += w;
      else if (s.def.blink && w > blinkWeight) {
        blinkInterval = s.def.blink;
        blinkWeight = w;
      }
    }
    // 2b. One-shot action (e.g. the "6 7" gesture): arm params are applied absolutely at the
    // end; head/face/mouth keys add on top so gaze, idle and the emotion still show through.
    this.actionArms.clear();
    this.actionPostPhysics.clear();
    this.mirrorArm.clear();
    this.actionWeight = 0;
    if (this.action) {
      const a = this.action;
      a.time += dt;
      const d = a.motion.duration;
      const w = smoothstep(Math.min(a.time / 0.2, (d - a.time) / 0.25, 1));
      a.motion.evaluate(a.time, (id, v) => {
        if (ARM_PARAMS.has(id)) this.actionArms.set(id, v);
        else if (PHYSICS_ARM_PARAMS.has(id)) this.actionPostPhysics.set(id, v);
        else this.add(id, w * (v - this.params.defaultOf(id)));
      });
      a.mirror?.evaluate(a.time, (id, v) => this.mirrorArm.set(id, v));
      this.actionWeight = w;
      gazeBias = { x: gazeBias.x, y: gazeBias.y, weight: gazeBias.weight + 0.5 * w }; // look at the viewer
      if (a.time >= d) {
        this.action = null;
        const def = EMOTIONS[this.emotion];
        this.rightArm.request(def.rightArm ?? null);
        this.leftArm.request(def.leftArm ?? null);
      }
    }
    if (gazeBias.weight > 0) {
      const total = gazeBias.weight;
      gazeBias = { x: gazeBias.x / Math.max(1, total), y: gazeBias.y / Math.max(1, total), weight: Math.min(1, total) };
    }

    // 3. Idle drift, breathing and fidgets.
    const talking = this.talk.speaking;
    if (this.options.idle) {
      const n = (i: number, speed: number) => this.noise[i].fbm(t * speed);
      this.add('AngleX', 4 * n(0, 0.22));
      this.add('AngleY', 3 * n(1, 0.18));
      this.add('AngleZ', 3.5 * n(2, 0.2));
      this.add('PositionX', 3 * n(3, 0.15));
      this.add('PositionZ', 3 * n(4, 0.17));
      this.add('PositionY', 1.5 * n(5, 0.25));
      const idleOnly = this.emotion === 'neutral' && !talking && !this.action && !this.gaze.trackingPointer;
      this.fidgets.update(dt, idleOnly, { add: (id, v) => this.add(id, v), set: (id, v) => this.add(id, v - this.value(id)) });
    }
    this.base.set('ParamBreath', 0.5 + 0.5 * Math.sin((t * 2 * Math.PI) / 3.6));

    // 4. Gaze: eyes lead, head follows; emotions can pull the gaze elsewhere.
    this.gaze.followPointer = this.options.followPointer;
    this.gaze.bias = gazeBias;
    this.gaze.update(dt);
    this.add('ParamEyeBallX', this.gaze.eye.x);
    this.add('ParamEyeBallY', this.gaze.eye.y);
    this.add('AngleX', this.gaze.head.x * 28);
    this.add('AngleY', this.gaze.head.y * 24);
    this.add('AngleZ', -this.gaze.head.x * this.gaze.head.y * 8);
    this.add('PositionX', this.gaze.head.x * 7);

    // 4b. Window dragging: her body trails the window and springs back, and physics swings her
    // hair. Positive PositionX and ParamBodyAngleZ move her right, and positive PositionY up.
    this.inertia.update(dt);
    const { lag } = this.inertia;
    const s = this.sway;
    this.add('PositionX', clamp(lag.x * s.position, -s.maxPosition, s.maxPosition));
    this.add('PositionY', clamp(-lag.y * s.position, -s.maxPosition, s.maxPosition));
    this.add('ParamBodyAngleZ', clamp(lag.x * s.tilt, -s.maxTilt, s.maxTilt));
    this.add('AngleZ', clamp(lag.x * s.headTilt, -s.maxTilt, s.maxTilt));

    // 5. Talking: mouth from the talker, emotion keeps the mouth shape; small head bobs.
    this.talk.update(dt);
    const e = this.talk.energy;
    if (e > 0.001 || this.talk.open > 0.001) {
      const poseOpen = this.value('ParamMouthOpenY');
      // While the voice sounds the talker owns the mouth, so lips can close on consonants even in
      // an open-mouthed emotion; in pauses the emotion's mouth returns.
      const open = clamp(poseOpen * (1 - this.talk.voiced) + this.talk.open * 1.15, 0, 1);
      this.add('ParamMouthOpenY', open - poseOpen);
      for (const v of VOWELS) this.add(`Param${v}`, this.talk.vowels[v] * this.talk.open);
      this.add('AngleY', 3 * this.talk.open + 2 * e * Math.sin(t * 6.5));
      this.add('AngleX', 2 * e * Math.sin(t * 2.3));
      this.add('ParamBrowLY', 0.2 * this.talk.open);
      this.add('ParamBrowRY', 0.2 * this.talk.open);
    }

    // 6. Blink: multiplies whatever eye openness the emotion asked for.
    this.blink.enabled = this.options.blink && noBlink < 0.5;
    this.blink.interval = blinkInterval;
    const b = this.blink.update(dt);
    for (const id of ['ParamEyeLOpen', 'ParamEyeROpen']) {
      const open = Math.max(0, this.value(id));
      this.add(id, open * b - open);
    }

    // Write everything we touched.
    const out = new Set([...this.base.keys(), ...this.acc.keys()]);
    for (const id of out) this.params.set(id, this.value(id));

    // 7. Arm pose motions override absolutely (they are authored by the rigger).
    const armOut = (id: string, v: number) => {
      if (!ARM_MOTION_SKIP.has(id)) this.params.set(id, v);
    };
    this.rightArm.update(dt, armOut);
    this.leftArm.update(dt, armOut);
    for (const [id, v] of this.actionArms) {
      // Pose toggles switch art; crossfading them would draw two half-transparent arms.
      const toggle = id.startsWith('Movement');
      this.params.set(id, toggle ? v : lerp(this.params.get(id), v, this.actionWeight));
    }
  }

  /** Runs after physics, before the model deforms: overrides physics-driven arm joints. */
  afterPhysics() {
    for (const [id, v] of this.actionPostPhysics) this.params.set(id, lerp(this.params.get(id), v, this.actionWeight));
  }
}
