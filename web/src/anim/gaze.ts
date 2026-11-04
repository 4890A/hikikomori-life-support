import { clamp, lerp, rand, Spring } from './math';

/**
 * Decides where she looks. Follows the pointer while it is active; otherwise wanders with
 * small saccades. Eyes react quickly and the head follows more slowly, which reads as
 * "noticing" rather than robotic tracking. All outputs are normalized to [-1, 1].
 */
export class Gaze {
  followPointer = true;
  /** Emotion-driven override: look here with this weight (0 = pointer/wander only). */
  bias = { x: 0, y: 0, weight: 0 };

  private pointer = { x: 0, y: 0, lastMove: -Infinity, inside: false };
  private wander = { x: 0, y: 0, next: 0 };
  private time = 0;
  private readonly eyeX = new Spring(0, 5);
  private readonly eyeY = new Spring(0, 5);
  private readonly headX = new Spring(0, 1.3);
  private readonly headY = new Spring(0, 1.3);

  eye = { x: 0, y: 0 };
  head = { x: 0, y: 0 };

  /** Pointer position relative to the face, normalized so ±1 is about half a screen away. */
  setPointer(x: number, y: number) {
    this.pointer.x = clamp(x, -1, 1);
    this.pointer.y = clamp(y, -1, 1);
    this.pointer.lastMove = this.time;
    this.pointer.inside = true;
  }

  pointerLeft() {
    this.pointer.inside = false;
  }

  get trackingPointer() {
    return this.followPointer && this.pointer.inside && this.time - this.pointer.lastMove < 4;
  }

  update(dt: number) {
    this.time += dt;
    if (this.time >= this.wander.next) {
      // Mostly glance around near the center, sometimes look further away.
      const far = Math.random() < 0.25;
      this.wander.x = rand(-1, 1) * (far ? 0.8 : 0.35);
      this.wander.y = rand(-0.6, 0.6) * (far ? 0.7 : 0.35);
      this.wander.next = this.time + rand(1.2, far ? 2.5 : 4.5);
    }
    let tx = this.trackingPointer ? this.pointer.x : this.wander.x;
    let ty = this.trackingPointer ? this.pointer.y : this.wander.y;
    tx = lerp(tx, this.bias.x, this.bias.weight);
    ty = lerp(ty, this.bias.y, this.bias.weight);

    this.eye.x = this.eyeX.update(tx, dt);
    this.eye.y = this.eyeY.update(ty, dt);
    // The head turns less than the eyes and lags behind them.
    this.head.x = this.headX.update(tx * 0.85, dt);
    this.head.y = this.headY.update(ty * 0.8, dt);
  }
}
