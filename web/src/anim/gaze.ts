import { clamp, lerp, rand, Spring } from './math';

const GLANCE_X = 0.7;
const GLANCE_Y = 0.05;
const GLANCE_WEIGHT = 0.85;
// While a window is shared, how often her idle gaze settles on it rather than on you.
const IDLE_SCREEN_CHANCE = 0.7;
const SCREEN_DRIFT_X = 0.12;
const SCREEN_DRIFT_Y = 0.08;

/**
 * Decides where she looks. Looks at the shared window while reacting to it, then follows the
 * pointer while it is active; otherwise wanders with small saccades. Eyes react quickly and the
 * head follows more slowly, which reads as "noticing" rather than robotic tracking. All outputs
 * are normalized to [-1, 1].
 */
export class Gaze {
  followPointer = true;
  /** Emotion-driven override: look here with this weight (0 = pointer/wander only). */
  bias = { x: 0, y: 0, weight: 0 };
  /** The direction of the shared window, when it's known. */
  screen: { x: number; y: number } | null = null;
  /** Set while she's talking about what's on screen. */
  watchingScreen = false;

  private pointer = { x: 0, y: 0, lastMove: -Infinity, inside: false };
  private wander = { x: 0, y: 0, next: 0 };
  private time = 0;
  private idleOnScreen = true;
  private drift = { x: 0, y: 0 };
  private glanceTarget = { x: 0, y: 0, until: 0 };
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

  /** Looks off to one side for a moment, as if something caught her eye. */
  glance(seconds = 0.8) {
    this.glanceTarget = this.screen
      ? { ...this.screen, until: this.time + seconds }
      : { x: Math.random() < 0.5 ? -GLANCE_X : GLANCE_X, y: GLANCE_Y, until: this.time + seconds };
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
      this.idleOnScreen = Math.random() < IDLE_SCREEN_CHANCE;
      this.drift = { x: rand(-SCREEN_DRIFT_X, SCREEN_DRIFT_X), y: rand(-SCREEN_DRIFT_Y, SCREEN_DRIFT_Y) };
    }
    const { screen } = this;
    let tx = this.wander.x;
    let ty = this.wander.y;
    if (screen && this.watchingScreen) {
      tx = screen.x + this.drift.x;
      ty = screen.y + this.drift.y;
    } else if (this.trackingPointer) {
      tx = this.pointer.x;
      ty = this.pointer.y;
    } else if (screen && this.idleOnScreen) {
      tx = screen.x + this.drift.x;
      ty = screen.y + this.drift.y;
    }
    tx = lerp(tx, this.bias.x, this.bias.weight);
    ty = lerp(ty, this.bias.y, this.bias.weight);
    if (this.time < this.glanceTarget.until) {
      tx = lerp(tx, this.glanceTarget.x, GLANCE_WEIGHT);
      ty = lerp(ty, this.glanceTarget.y, GLANCE_WEIGHT);
    }

    this.eye.x = this.eyeX.update(tx, dt);
    this.eye.y = this.eyeY.update(ty, dt);
    // The head turns less than the eyes and lags behind them.
    this.head.x = this.headX.update(tx * 0.85, dt);
    this.head.y = this.headY.update(ty * 0.8, dt);
  }
}
