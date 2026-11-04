import { smoothstep } from './math';

/** Writes into the emotion layer; values are scaled by the emotion's blend weight. */
export interface EmotionWriter {
  /** Offset a parameter from its pose value. */
  add(id: string, value: number): void;
  /** Override a parameter's target (still crossfaded by the emotion weight). */
  set(id: string, value: number): void;
}

export interface GazeBias {
  x: number;
  y: number;
  weight: number;
}

export type ArmPose = 'finger' | 'grass' | 'chest';

export interface Emotion {
  label: string;
  /** Static parameter targets, crossfaded in/out. */
  pose: Record<string, number>;
  /** Procedural motion layered on top of the pose; `t` is seconds since the emotion began. */
  animate?: (t: number, out: EmotionWriter) => void;
  /** Where she looks instead of (or partially instead of) the pointer. */
  gaze?: GazeBias | ((t: number) => GazeBias);
  /** Blink interval range in seconds, or false when the eyes are drawn closed/replaced. */
  blink?: [number, number] | false;
  rightArm?: 'finger' | 'grass';
  leftArm?: 'chest';
  /** One-shot reactions return to the previous emotion after this many seconds. */
  duration?: number;
}

const EYES = (v: number) => ({ ParamEyeLOpen: v, ParamEyeROpen: v });
const BROWS = (v: number) => ({ ParamBrowLY: v, ParamBrowRY: v });

/** A repeating 0→1→0 pulse of `width` seconds every `period` seconds. */
const pulse = (t: number, period: number, width: number, offset = 0) => {
  const p = (t + offset) % period;
  return p < width ? Math.sin((p / width) * Math.PI) : 0;
};

export const EMOTIONS: Record<string, Emotion> = {
  neutral: { label: 'Neutral', pose: {} },

  happy: {
    label: 'Happy',
    pose: { EyeSmile: 1, ParamMouthForm: 1, ParamMouthOpenY: 0.35, ...BROWS(0.35), key7: 0.35 },
    animate(t, o) {
      // Opens with a beaming ^^ squint, then smiling eyes with the odd giggle-squint.
      const squint = Math.max(1 - smoothstep((t - 1.2) / 0.35), pulse(t, 4.2, 0.9, 1.5));
      o.set('ParamEyeLOpen', 0.8 * (1 - squint));
      o.set('ParamEyeROpen', 0.8 * (1 - squint));
      o.add('ParamMouthOpenY', 0.2 * squint);
      o.add('AngleZ', 7 * Math.sin(t * 2.1));
      o.add('PositionX', 2.5 * Math.sin(t * 2.1 + 0.6));
      o.add('PositionY', 2 * Math.abs(Math.sin(t * 2.1)));
    },
    gaze: { x: 0, y: 0.05, weight: 0.25 },
  },

  excited: {
    label: 'Excited',
    pose: { ...EYES(1.25), ...BROWS(1), ParamMouthOpenY: 0.8, ParamMouthForm: 1, EyeSmile: 0.3, LeanInput: -16, key7: 0.5 },
    animate(t, o) {
      const hop = Math.abs(Math.sin(t * Math.PI * 2.2));
      o.add('PositionY', 10 * hop - 4);
      o.add('AngleY', 5 * hop);
      o.add('AngleZ', 6 * Math.sin(t * Math.PI * 2.2));
      o.add('ParamMouthOpenY', 0.15 * Math.sin(t * 9));
      // Every few seconds squeeze the eyes shut in delight.
      const squeal = pulse(t, 3.6, 0.7, 1.8);
      o.set('EyeSmile', 0.3 + 0.7 * squeal);
      o.add('ParamEyeLOpen', -1.25 * squeal);
      o.add('ParamEyeROpen', -1.25 * squeal);
    },
    gaze: { x: 0, y: 0.1, weight: 0.4 },
    blink: [1.4, 3],
  },

  embarrassed: {
    label: 'Embarrassed',
    pose: {
      key5: 1, key7: 1, key13: 1, BrowInnerUp: 1, ...BROWS(-0.6),
      ParamMouthForm: -0.6, ParamMouthOpenY: 0.12, AngleX: -10, AngleY: -10, AngleZ: 9, PositionX: -4,
    },
    animate(t, o) {
      // Flustered trembling plus a slower squirm.
      o.add('PositionX', 1.3 * Math.sin(t * 11));
      o.add('AngleX', 2.5 * Math.sin(t * 13));
      o.add('AngleZ', 3 * Math.sin(t * 1.7));
      o.add('ParamMouthOpenY', 0.08 * Math.sin(t * 7));
    },
    gaze: { x: -0.5, y: -0.4, weight: 0.7 },
    blink: false,
    leftArm: 'chest',
  },

  flushed: {
    label: 'Flushed',
    pose: {
      key7: 1, ...EYES(0.72), BrowInnerUp: 1, ...BROWS(-0.25),
      ParamMouthForm: -0.4, Mouthpucker: 0.6, CheeckPuff: 0.25, AngleZ: -7, AngleY: -6,
    },
    animate(t, o) {
      o.add('AngleZ', 2 * Math.sin(t * 1.3));
      o.add('PositionX', 1.5 * Math.sin(t * 0.9));
    },
    // Shyly looks away, sneaking a glance back every few seconds.
    gaze: (t) => ({ x: 0.6, y: -0.45, weight: 0.85 * (1 - pulse(t, 3.8, 1.1, 0.5)) }),
    blink: [1.1, 2.8],
  },

  thinking: {
    label: 'Thinking',
    pose: {
      ...EYES(0.85), ParamBrowLY: 0.6, ParamBrowRY: -0.3, ParamMouthForm: -0.35,
      MouthX: 0.6, AngleX: -10, AngleY: 8, AngleZ: 9,
    },
    animate(t, o) {
      o.add('AngleZ', 4 * Math.sin(t * 0.9));
      o.add('AngleX', 3 * Math.sin(t * 0.45));
      o.add('MouthX', 0.3 * Math.sin(t * 1.1));
      // "Loading..." spinner fades in if she ponders for a while.
      o.set('key8', smoothstep((t - 3) / 0.6));
      o.set('Param140', (t * 0.9) % 1);
    },
    gaze: (t) => ({ x: -0.45 + 0.2 * Math.sin(t * 0.7), y: 0.75, weight: 0.85 }),
    blink: [3, 6.5],
    rightArm: 'finger',
  },

  surprised: {
    label: 'Surprised',
    pose: { ...EYES(1.4), ...BROWS(1), ParamMouthOpenY: 0.75, JawOpen: 0.4, ParamMouthForm: -0.2, BrowInnerUp: 0.3 },
    animate(t, o) {
      const jolt = Math.exp(-t * 4);
      o.add('PositionY', 10 * jolt);
      o.add('AngleY', 9 * jolt);
      o.add('LeanInput', 12 * jolt);
    },
    gaze: { x: 0, y: 0, weight: 0.5 },
    blink: [4, 7],
    duration: 2.5,
  },

  sad: {
    label: 'Sad',
    pose: { key2: 1, BrowInnerUp: 1, ...BROWS(-0.8), ...EYES(0.7), ParamMouthForm: -1, AngleY: -10, AngleZ: -4 },
    animate(t, o) {
      o.add('PositionY', -1.5 + 1.5 * Math.sin(t * 0.8)); // slow sniffly breathing
    },
    gaze: { x: -0.2, y: -0.6, weight: 0.6 },
    blink: [2, 4],
  },

  love: {
    label: 'Love',
    pose: { key4: 1, key7: 0.8, ParamMouthForm: 1, ParamMouthOpenY: 0.25, LeanInput: -10 },
    animate(t, o) {
      o.add('AngleZ', 6 * Math.sin(t * 1.6));
      o.add('PositionX', 3 * Math.sin(t * 1.6 + 0.5));
    },
    gaze: { x: 0, y: 0.05, weight: 0.5 },
    leftArm: 'chest',
  },

  smug: {
    label: 'Smug',
    pose: { key6: 1, ParamMouthForm: 0.6, AngleZ: 8, AngleY: 5, ParamBrowLY: 0.3 },
    animate(t, o) {
      o.add('AngleZ', 2 * Math.sin(t * 1.1));
    },
    gaze: { x: 0.1, y: 0, weight: 0.3 },
    blink: [3, 6],
    rightArm: 'grass',
  },

  dizzy: {
    label: 'Dizzy',
    pose: { key3: 1, key13: 1, ParamMouthOpenY: 0.3, ParamMouthForm: -0.5, ...BROWS(-0.4) },
    animate(t, o) {
      o.add('AngleX', 12 * Math.cos(t * 3.2));
      o.add('AngleZ', 10 * Math.sin(t * 3.2));
      o.add('PositionX', 4 * Math.cos(t * 3.2));
    },
    blink: false,
    duration: 3.5,
  },

  pout: {
    label: 'Pout',
    pose: { CheeckPuff: 1, Mouthpucker: 0.5, ...BROWS(-0.7), key7: 0.4, AngleZ: -8, AngleX: 8 },
    animate(t, o) {
      o.add('AngleX', 2 * Math.sin(t * 0.8));
    },
    gaze: { x: 0.55, y: 0, weight: 0.6 },
  },

  worried: {
    label: 'Worried',
    pose: { key13: 1, BrowInnerUp: 1, ...BROWS(-0.35), ...EYES(0.95), ParamMouthForm: -0.5, AngleY: -4 },
    animate(t, o) {
      o.add('AngleX', 2.5 * Math.sin(t * 1.9));
      o.add('PositionX', 0.6 * Math.sin(t * 9));
    },
    gaze: (t) => ({ x: 0.35 * Math.sin(t * 1.4), y: -0.25, weight: 0.5 }),
    blink: [1.2, 3],
  },

  sigh: {
    label: 'Sigh',
    pose: { BrowInnerUp: 0.5, ...BROWS(-0.2), ...EYES(0.4), ParamMouthForm: -0.2 },
    animate(t, o) {
      // Shoulders and head settle as the breath goes out.
      const exhale = Math.min(1, t / 0.8);
      o.add('AngleY', -9 * exhale);
      o.add('PositionY', -5 * exhale);
      o.add('LeanInput', 5 * exhale);
    },
    gaze: { x: -0.2, y: -0.5, weight: 0.6 },
    blink: [4, 7],
  },

  sleepy: {
    label: 'Sleepy',
    pose: { ...EYES(0.35), ...BROWS(-0.3), AngleZ: 7, AngleY: -5 },
    animate(t, o) {
      o.add('AngleY', 4 * Math.sin(t * 0.9));
      o.add('AngleZ', 2.5 * Math.sin(t * 0.5));
    },
    gaze: { x: 0, y: -0.3, weight: 0.5 },
    blink: [1.5, 3],
  },
};
