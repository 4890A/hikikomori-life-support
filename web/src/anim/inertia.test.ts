import { describe, expect, it } from 'vitest';
import { Inertia } from './inertia';

const run = (inertia: Inertia, seconds: number) => {
  for (let t = 0; t < seconds; t += 1 / 60) inertia.update(1 / 60);
};

describe('Inertia', () => {
  it('does nothing until the window moves', () => {
    const inertia = new Inertia();
    inertia.setAnchor({ x: 500, y: 300 });
    run(inertia, 1);
    expect(inertia.lag).toEqual({ x: 0, y: 0 });
  });

  it('trails a moved window, swings past, then settles', () => {
    const inertia = new Inertia();
    inertia.setAnchor({ x: 500, y: 300 });
    inertia.setAnchor({ x: 600, y: 300 });
    expect(inertia.lag.x).toBe(-100);
    let overshoot = -Infinity;
    for (let t = 0; t < 1; t += 1 / 60) {
      inertia.update(1 / 60);
      overshoot = Math.max(overshoot, inertia.lag.x);
    }
    expect(overshoot).toBeGreaterThan(10);
    run(inertia, 4);
    expect(Math.abs(inertia.lag.x)).toBeLessThan(0.5);
  });

  it("isn't flung by a window snapped across the screen", () => {
    const inertia = new Inertia();
    inertia.setAnchor({ x: 0, y: 0 });
    inertia.setAnchor({ x: 3000, y: -2000 });
    expect(inertia.lag).toEqual({ x: -220, y: 220 });
  });

  it("doesn't treat finding the window again as a movement", () => {
    const inertia = new Inertia();
    inertia.setAnchor({ x: 0, y: 0 });
    inertia.setAnchor(null);
    inertia.setAnchor({ x: 900, y: 0 });
    expect(inertia.lag).toEqual({ x: 0, y: 0 });
  });

  it('stays stable through a long frame', () => {
    const inertia = new Inertia();
    inertia.setAnchor({ x: 0, y: 0 });
    inertia.setAnchor({ x: 200, y: 0 });
    inertia.update(2);
    expect(Number.isFinite(inertia.lag.x)).toBe(true);
    expect(Math.abs(inertia.lag.x)).toBeLessThan(200);
  });
});
