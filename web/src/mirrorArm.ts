import type { Live2DModel } from 'pixi-live2d-display-lipsyncpatch/cubism4';
import { drawablesUnderPart, filterDrawables, loadRig, type Params, type Rig } from './live2d';

// The rig's open posed hand ("hand on chest" arm, toggled by Movement2) exists only on her left.
const OPEN_HAND_ARM = 'Part52';
// Horizontal pose params change sign when the pose is copied onto the mirrored instance.
const FLIPPED = /^(Param)?(Body)?Angle(R)?[XZ]\d?$|^Position[XZ]$|^Shoulder[XZ]$|^(Param)?HipAngle[XZ]\d?$|^HipZ\d$|^LEGAngleZ\d?$|^Param(44|25)$/;

/**
 * A second, horizontally mirrored instance of the model that draws only the left open-hand arm,
 * so it can stand in for a right open hand (the rig has none). Each frame it copies the main
 * model's final pose (sign-flipped where horizontal) and takes its own arm values.
 * Only updated and drawn while `active`.
 */
export class MirrorArm {
  private readonly snapshot: Float32Array;
  private readonly flipped: boolean[];
  private arm = new Map<string, number>();
  private active = false;

  private constructor(
    private readonly main: Rig,
    private readonly mirror: Rig,
  ) {
    this.snapshot = new Float32Array(main.params.values.length);
    this.flipped = main.params.ids.map((id) => FLIPPED.test(id));
  }

  static async create(url: string, main: Rig) {
    let self: MirrorArm | null = null;
    const mirror = await loadRig(url, () => self?.applyPose());
    const internal = mirror.model.internalModel as any;
    internal.physics = undefined; // pose comes from the main model, physics included
    const keep = drawablesUnderPart(mirror.model, OPEN_HAND_ARM);
    const others = new Set(Array.from({ length: internal.coreModel.getDrawableCount() }, (_, i) => i).filter((i) => !keep.has(i)));
    filterDrawables(mirror.model, others, () => true);
    mirror.model.visible = false;
    mirror.model.automator.autoUpdate = false;
    self = new MirrorArm(main, mirror);
    return self;
  }

  get model(): Live2DModel {
    return this.mirror.model;
  }

  /** Call after the main model's physics each frame. */
  capture(active: boolean, arm: Map<string, number>) {
    this.snapshot.set(this.main.params.values);
    this.arm = arm;
    if (active !== this.active) {
      this.active = active;
      this.mirror.model.visible = active;
      this.mirror.model.automator.autoUpdate = active;
    }
  }

  /** Mirrors the main model's on-screen transform around her vertical center line. */
  syncTransform() {
    const { model } = this.main;
    const s = model.scale.x;
    this.mirror.model.scale.set(-s, model.scale.y);
    this.mirror.model.position.set(model.position.x + model.internalModel.width * s, model.position.y);
  }

  private applyPose() {
    const values: Params['values'] = this.mirror.params.values;
    for (let i = 0; i < values.length; i++) values[i] = this.flipped[i] ? -this.snapshot[i] : this.snapshot[i];
    for (const [id, v] of this.arm) this.mirror.params.set(id, v);
  }
}
