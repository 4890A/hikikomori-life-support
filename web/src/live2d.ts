import * as PIXI from 'pixi.js';
// The lipsyncpatch fork bundles a newer Cubism framework with multiply/screen color support,
// which this model uses (e.g. the nose patch renders black without it).
import { Live2DModel } from 'pixi-live2d-display-lipsyncpatch/cubism4';

Live2DModel.registerTicker(PIXI.Ticker);

// Reserve the Cubism Core heap before any model loads. If the heap has to grow (e.g. when the
// mirrored second instance loads), models created earlier keep typed-array views into the old
// buffer: their parameter writes stop reaching the core and they silently freeze.
(window as any).Live2DCubismCore.Memory.initializeAmountOfMemory(128 * 1024 * 1024);

/** Direct, index-cached access to the Cubism Core parameter arrays. */
export class Params {
  readonly ids: string[];
  readonly min: Float32Array;
  readonly max: Float32Array;
  readonly defaults: Float32Array;
  /** The live Cubism parameter array (writes take effect on the next model update). */
  readonly values: Float32Array;
  private readonly index = new Map<string, number>();

  constructor(coreParams: { ids: string[]; values: Float32Array; minimumValues: Float32Array; maximumValues: Float32Array; defaultValues: Float32Array }) {
    this.ids = coreParams.ids;
    this.values = coreParams.values;
    this.min = coreParams.minimumValues;
    this.max = coreParams.maximumValues;
    this.defaults = coreParams.defaultValues;
    this.ids.forEach((id, i) => this.index.set(id, i));
  }

  has(id: string) {
    return this.index.has(id);
  }

  defaultOf(id: string) {
    const i = this.index.get(id);
    return i === undefined ? 0 : this.defaults[i];
  }

  get(id: string) {
    const i = this.index.get(id);
    return i === undefined ? 0 : this.values[i];
  }

  set(id: string, value: number) {
    const i = this.index.get(id);
    if (i === undefined) return;
    this.values[i] = Math.min(this.max[i], Math.max(this.min[i], value));
  }
}

export interface Rig {
  model: Live2DModel;
  params: Params;
}

/** Indices of all drawables inside `partId` (including nested parts). */
export function drawablesUnderPart(model: Live2DModel, partId: string): Set<number> {
  const core = (model.internalModel as any).coreModel.getModel();
  const { parts, drawables } = core;
  const inside = new Set<number>([parts.ids.indexOf(partId)]);
  for (let grew = true; grew; ) {
    grew = false;
    for (let i = 0; i < parts.count; i++) {
      if (!inside.has(i) && inside.has(parts.parentIndices[i])) {
        inside.add(i);
        grew = true;
      }
    }
  }
  const out = new Set<number>();
  for (let i = 0; i < drawables.count; i++) if (inside.has(drawables.parentPartIndices[i])) out.add(i);
  return out;
}

/** Skips drawing the given drawables while `hidden()` returns true (renderer-level filter). */
export function filterDrawables(model: Live2DModel, drawables: Set<number>, hidden: () => boolean) {
  const core = (model.internalModel as any).coreModel;
  const isVisible = core.getDrawableDynamicFlagIsVisible.bind(core);
  core.getDrawableDynamicFlagIsVisible = (i: number) => isVisible(i) && !(drawables.has(i) && hidden());
}

/**
 * Loads the model and replaces pixi-live2d-display's built-in focus, breath and blink with
 * `onFrame`, which runs every frame after motions/expressions and right before physics.
 * This rig routes head/body movement through physics inputs (AngleX, PositionX, ...), so
 * writing those here lets the rigger's physics smooth and propagate them.
 */
export async function loadRig(url: string, onFrame: (dt: number) => void, onAfterPhysics?: () => void): Promise<Rig> {
  const model = await Live2DModel.from(url, { autoHitTest: false, autoFocus: false, autoUpdate: true });
  const internal = model.internalModel as any;
  const params = new Params(internal.coreModel.getModel().parameters);

  // The library initializes clipping with one mask render texture (max 36 clip contexts) at
  // 256px; this model needs 49 contexts and looks jagged at 256. Re-init before the first draw.
  const renderer = internal.renderer;
  renderer.initialize(internal.coreModel, 2);
  renderer.setIsPremultipliedAlpha(true);
  renderer.setClippingMaskBufferSize(2048);

  internal.eyeBlink = undefined;
  internal.breath = undefined;
  internal.updateNaturalMovements = () => {};
  let last = performance.now();
  internal.updateFocus = () => {
    const now = performance.now();
    const dt = Math.min(0.1, (now - last) / 1000);
    last = now;
    onFrame(dt);
  };
  // Some arm params are physics outputs (sway); gestures override them after physics runs.
  if (onAfterPhysics) internal.on('beforeModelUpdate', onAfterPhysics);
  return { model, params };
}
