import { describe, expect, it } from 'vitest';
import { gazeOffset, pageToDesktop, windowHandle } from './desktopGaze';

describe('windowHandle', () => {
  it('reads the handle from a shared window', () => {
    expect(windowHandle({ label: 'window:42404830:0', surface: 'window' })).toBe(42404830);
  });

  it('has none for a whole screen, a tab or nothing', () => {
    expect(windowHandle({ label: 'screen:0:0', surface: 'monitor' })).toBe(0);
    expect(windowHandle({ label: 'web-contents-media-stream://1:2', surface: 'browser' })).toBe(0);
    expect(windowHandle(null)).toBe(0);
  });
});

describe('pageToDesktop', () => {
  it('measures from the bottom of the window, below the browser toolbars, at 150% scaling', () => {
    const page = { left: 100, top: 50, right: 1900, bottom: 1450 };
    expect(pageToDesktop(page, { x: 200, y: 700 }, 800, 1.5)).toEqual({ x: 400, y: 1300 });
  });

  it('works on a monitor left of the main one', () => {
    const page = { left: -1920, top: 0, right: 0, bottom: 1080 };
    expect(pageToDesktop(page, { x: 100, y: 1000 }, 1000, 1).x).toBe(-1820);
  });
});

describe('gazeOffset', () => {
  const face = { x: 1000, y: 500 };

  it('makes up positive and right positive', () => {
    expect(gazeOffset({ x: 1500, y: 250 }, face, 1000)).toEqual({ x: 0.5, y: 0.25 });
  });

  it('keeps the direction of something far away', () => {
    const { x, y } = gazeOffset({ x: 5000, y: -1500 }, face, 1000);
    expect(x).toBe(1);
    expect(y).toBe(0.5);
  });

  it('stays inside a smaller limit', () => {
    expect(gazeOffset({ x: -9000, y: 500 }, face, 1000, 0.8)).toEqual({ x: -0.8, y: 0 });
  });

  it('copes with a target right on her face', () => {
    expect(gazeOffset(face, face, 1000)).toEqual({ x: 0, y: 0 });
  });
});
