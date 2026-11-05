import type { Gaze } from '../anim/gaze';

const STREAM_URL = '/speech/desktop/stream';
// Same scale as following the mouse over her page: a full turn at about half a screen away.
const REACH = 0.45;
// She turns toward the shared window without straining, even if it's on another monitor.
const SCREEN_TURN = 0.8;

export type SharedSide = 'auto' | 'left' | 'right';
export interface ShareSource {
  label: string;
  surface: string | undefined;
}
interface Rect {
  left: number;
  top: number;
  right: number;
  bottom: number;
}
interface Point {
  x: number;
  y: number;
}
interface DesktopState {
  cursor: [number, number];
  page: Rect | null;
  target: Rect | null;
}

/** The Windows handle in a shared window's track label, such as window:42404830:0. */
export function windowHandle(source: ShareSource | null) {
  const match = source?.surface === 'window' ? /^window:(\d+):/.exec(source.label) : null;
  return match ? Number(match[1]) : 0;
}

/** A point on the page, in physical desktop pixels. The page fills its window up to the bottom edge. */
export function pageToDesktop(page: Rect, point: Point, innerHeight: number, scale: number): Point {
  return { x: page.left + point.x * scale, y: page.bottom - (innerHeight - point.y) * scale };
}

/** Where to look, from -1 to 1 with up positive. A far target keeps its direction rather than its distance. */
export function gazeOffset(target: Point, from: Point, reach: number, limit = 1): Point {
  const x = (target.x - from.x) / reach;
  const y = (from.y - target.y) / reach;
  const shrink = Math.min(1, limit / Math.max(Math.abs(x), Math.abs(y), Number.EPSILON));
  return { x: x * shrink, y: y * shrink };
}

/** Points her gaze at the mouse anywhere on the desktop, and at the window you're sharing. */
export class DesktopGaze {
  /** Called when the description of what she's looking towards changes. */
  onStatus?: (status: string) => void;

  private side: SharedSide = 'auto';
  private source: ShareSource | null = null;
  private events: EventSource | null = null;
  private state: DesktopState | null = null;
  private page: Rect | null = null;
  private lastCursor = '';
  private status = '';

  constructor(
    private readonly gaze: Gaze,
    private readonly faceOnPage: () => Point,
  ) {
    this.connect();
  }

  /** True while the bridge is telling her where the mouse is, so the page's own mouse events aren't needed. */
  get live() {
    return this.state !== null && this.page !== null;
  }

  /** What's being shared, or null when it stops. */
  share(source: ShareSource | null) {
    const changed = windowHandle(source) !== windowHandle(this.source);
    this.source = source;
    if (changed) this.connect();
    this.update();
  }

  setSide(side: SharedSide) {
    this.side = side;
    this.update();
  }

  /** Call every frame, as her face moves too. */
  update() {
    this.gaze.screen = this.screenTarget();
    this.setStatus(this.describe());
  }

  private screenTarget(): Point | null {
    if (!this.source) return null;
    if (this.side !== 'auto') return { x: this.side === 'left' ? -SCREEN_TURN : SCREEN_TURN, y: 0 };
    const target = this.state?.target;
    if (!target) return null;
    const center = { x: (target.left + target.right) / 2, y: (target.top + target.bottom) / 2 };
    return this.fromFace(center, SCREEN_TURN);
  }

  private describe() {
    if (!this.source) return 'Nothing shared yet';
    if (this.side !== 'auto') return `Looks to the ${this.side} when reacting`;
    if (this.state?.target) return 'Found the shared window';
    if (windowHandle(this.source)) return "Can't see the shared window. Is it minimized?";
    return "Can't tell where this share is, so choose a side";
  }

  private connect() {
    this.events?.close();
    this.state = null;
    const query = new URLSearchParams({ page: document.title, window: String(windowHandle(this.source)) });
    this.events = new EventSource(`${STREAM_URL}?${query}`);
    this.events.onmessage = (event) => this.receive(JSON.parse(event.data));
    // The browser reconnects by itself, and until then the page's own mouse events take over.
    this.events.onerror = () => {
      this.state = null;
    };
  }

  private receive(state: DesktopState) {
    this.state = state;
    // She's only found while her tab is showing, and can't be seen otherwise anyway.
    this.page = state.page ?? this.page;
    const cursor = state.cursor.join();
    if (cursor === this.lastCursor) return;
    this.lastCursor = cursor;
    if (!this.page) return;
    const { x, y } = this.fromFace({ x: state.cursor[0], y: state.cursor[1] }, 1);
    this.gaze.setPointer(x, y);
  }

  private fromFace(target: Point, limit: number): Point {
    if (!this.page) return { x: 0, y: 0 };
    const scale = window.devicePixelRatio;
    const face = pageToDesktop(this.page, this.faceOnPage(), window.innerHeight, scale);
    return gazeOffset(target, face, Math.max(window.innerWidth, window.innerHeight) * REACH * scale, limit);
  }

  private setStatus(status: string) {
    if (status === this.status) return;
    this.status = status;
    this.onStatus?.(status);
  }
}
