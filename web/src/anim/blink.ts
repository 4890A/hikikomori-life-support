import { rand } from './math';

/**
 * Natural blinking: randomized intervals, occasional double blinks, and an asymmetric curve
 * (fast close, short hold, slower open). `value` is an eye-openness multiplier in [0, 1].
 */
export class Blinker {
  value = 1;
  enabled = true;
  /** Seconds between blinks; emotions can shorten it (nervous) or lengthen it (focused). */
  interval: [number, number] = [2.2, 5.5];
  private t = 0;
  private next = rand(1, 3);
  private phase = -1;
  private pendingDouble = false;

  static readonly CLOSE = 0.07;
  static readonly HOLD = 0.04;
  static readonly OPEN = 0.14;

  trigger() {
    if (this.phase < 0) this.phase = 0;
  }

  update(dt: number) {
    this.t += dt;
    if (this.phase < 0) {
      if (this.enabled && this.t >= this.next) {
        this.phase = 0;
        this.t = 0;
      }
      this.value = 1;
      return this.value;
    }
    this.phase += dt;
    const { CLOSE, HOLD, OPEN } = Blinker;
    const p = this.phase;
    if (p < CLOSE) this.value = 1 - p / CLOSE;
    else if (p < CLOSE + HOLD) this.value = 0;
    else if (p < CLOSE + HOLD + OPEN) {
      const u = (p - CLOSE - HOLD) / OPEN;
      this.value = 1 - (1 - u) * (1 - u);
    } else {
      this.value = 1;
      this.phase = -1;
      this.t = 0;
      if (!this.pendingDouble && Math.random() < 0.15) {
        this.pendingDouble = true;
        this.next = 0.12;
      } else {
        this.pendingDouble = false;
        this.next = rand(this.interval[0], this.interval[1]);
      }
    }
    return this.value;
  }
}
