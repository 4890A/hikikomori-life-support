import { startClock } from './clock';

// Tiny frames are enough to see that something happened, and cheap to compare.
const THUMB_WIDTH = 64;
const THUMB_HEIGHT = 36;
const CHECK_INTERVAL_MS = 500;
// A pixel counts as changed past this brightness difference, out of 255.
const PIXEL_THRESHOLD = 24;
const FRAME_WIDTH = 768;
const FRAME_QUALITY = 0.8;

/** Watches a video stream of a shared window and reports how much of the frame changes between checks. */
export class ScreenWatcher {
  /** Called with the share of pixels that changed, from 0 to 1. */
  onChange?: (fraction: number) => void;
  onEnded?: () => void;

  private readonly video = document.createElement('video');
  private readonly thumb = document.createElement('canvas');
  private readonly thumbContext: CanvasRenderingContext2D;
  private readonly frameCanvas = document.createElement('canvas');
  private previous: Uint8ClampedArray | null = null;
  private stopClock: (() => void) | null = null;

  constructor(private readonly stream: MediaStream) {
    this.thumb.width = THUMB_WIDTH;
    this.thumb.height = THUMB_HEIGHT;
    this.thumbContext = this.thumb.getContext('2d', { willReadFrequently: true })!;
    this.video.muted = true;
    this.video.playsInline = true;
    this.video.srcObject = stream;
    stream.getVideoTracks()[0]?.addEventListener('ended', () => this.onEnded?.());
  }

  /** Asks the browser for a window to watch. Must be called from a click handler. */
  static async fromDisplay() {
    const stream = await navigator.mediaDevices.getDisplayMedia({ video: { frameRate: 5 }, audio: false });
    return new ScreenWatcher(stream);
  }

  async start() {
    await this.video.play();
    this.stopClock = startClock(CHECK_INTERVAL_MS, () => this.check());
  }

  stop() {
    this.stopClock?.();
    this.stopClock = null;
    this.stream.getTracks().forEach((track) => track.stop());
    this.video.srcObject = null;
    this.previous = null;
  }

  /** The current frame as a JPEG data URL, about 768 px wide. */
  frame(): string {
    const scale = Math.min(1, FRAME_WIDTH / this.video.videoWidth);
    this.frameCanvas.width = Math.round(this.video.videoWidth * scale);
    this.frameCanvas.height = Math.round(this.video.videoHeight * scale);
    this.frameCanvas.getContext('2d')!.drawImage(this.video, 0, 0, this.frameCanvas.width, this.frameCanvas.height);
    return this.frameCanvas.toDataURL('image/jpeg', FRAME_QUALITY);
  }

  private check() {
    if (this.video.videoWidth === 0) return;
    this.thumbContext.drawImage(this.video, 0, 0, THUMB_WIDTH, THUMB_HEIGHT);
    const { data } = this.thumbContext.getImageData(0, 0, THUMB_WIDTH, THUMB_HEIGHT);
    const gray = new Uint8ClampedArray(THUMB_WIDTH * THUMB_HEIGHT);
    for (let i = 0; i < gray.length; i += 1) {
      gray[i] = 0.299 * data[i * 4] + 0.587 * data[i * 4 + 1] + 0.114 * data[i * 4 + 2];
    }
    if (this.previous) {
      let changed = 0;
      for (let i = 0; i < gray.length; i += 1) {
        if (Math.abs(gray[i] - this.previous[i]) > PIXEL_THRESHOLD) changed += 1;
      }
      this.onChange?.(changed / gray.length);
    }
    this.previous = gray;
  }
}
