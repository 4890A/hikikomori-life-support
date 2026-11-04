/**
 * Calls back at a steady rate, even while the page is hidden. Browsers slow page timers when a
 * game covers the window, sometimes to once a minute, but leave timers inside workers alone.
 * Returns a function that stops the clock.
 */
export function startClock(intervalMs: number, tick: () => void): () => void {
  const source = `setInterval(() => postMessage(0), ${intervalMs});`;
  const url = URL.createObjectURL(new Blob([source], { type: 'text/javascript' }));
  const worker = new Worker(url);
  URL.revokeObjectURL(url);
  worker.onmessage = tick;
  return () => worker.terminate();
}
