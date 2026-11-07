import { clamp } from './math';

// She hangs inside her window on a soft spring: when the window moves she lags behind, then
// swings back past where she started and settles. About 1.4 swings a second, with a little bounce.
const FREQUENCY_HZ = 1.4;
const DAMPING_RATIO = 0.32;
const STIFFNESS = (2 * Math.PI * FREQUENCY_HZ) ** 2;
const DAMPING = 2 * DAMPING_RATIO * Math.sqrt(STIFFNESS);
// A window snapped across the screen shouldn't fling her off it.
const MAX_LAG = 220;
// Longer frames are split up, so a stalled tab can't blow the spring up.
const MAX_STEP = 1 / 120;

export interface Point {
  x: number;
  y: number;
}

/**
 * How far her body trails her window as it's dragged, in CSS pixels with down positive. Feed it the
 * window's position each frame and read `lag`.
 */
export class Inertia {
  lag: Point = { x: 0, y: 0 };
  private velocity: Point = { x: 0, y: 0 };
  private anchor: Point | null = null;

  /** Where her window is now, or null when that isn't known. */
  setAnchor(anchor: Point | null) {
    // Starting, or losing track and finding it again, isn't a movement.
    if (!anchor || !this.anchor) this.reset();
    if (anchor && this.anchor) {
      this.lag.x -= anchor.x - this.anchor.x;
      this.lag.y -= anchor.y - this.anchor.y;
      this.lag.x = clamp(this.lag.x, -MAX_LAG, MAX_LAG);
      this.lag.y = clamp(this.lag.y, -MAX_LAG, MAX_LAG);
    }
    this.anchor = anchor;
  }

  update(dt: number) {
    let left = Math.min(dt, 0.25);
    while (left > 0) {
      const step = Math.min(left, MAX_STEP);
      left -= step;
      for (const axis of ['x', 'y'] as const) {
        const accel = -STIFFNESS * this.lag[axis] - DAMPING * this.velocity[axis];
        this.velocity[axis] += accel * step;
        this.lag[axis] += this.velocity[axis] * step;
      }
    }
  }

  private reset() {
    this.lag = { x: 0, y: 0 };
    this.velocity = { x: 0, y: 0 };
  }
}
