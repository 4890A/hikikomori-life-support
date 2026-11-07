import type { PreparedLine, SpeechPlayer } from '../anim/speech';
import { el } from '../dom';
import type { Director } from './director';

const STORAGE_KEY = 'companion-show-monitor';
const TICK_MS = 100;

function loadPreference() {
  try {
    return localStorage.getItem(STORAGE_KEY) !== 'off';
  } catch {
    return true; // Storage can be blocked; showing it is the useful default.
  }
}

function savePreference(on: boolean) {
  try {
    localStorage.setItem(STORAGE_KEY, on ? 'on' : 'off');
  } catch {
    // Only the choice isn't remembered.
  }
}

/** Where a line has got to, and how long it took: Model, Writing, TTS, then playing. */
function stepTimes(line: PreparedLine, now: number) {
  const { writing, tts, ready, speaking } = line.stages;
  const span = (start: number | undefined, end: number | undefined) => (start === undefined ? null : (end ?? now) - start);
  return [span(line.requestedAt, writing ?? tts ?? ready), span(writing, tts ?? ready), span(tts, ready), speaking === undefined ? null : now - speaking];
}

function waitingOn(line: PreparedLine) {
  if (line.failed) return 'Failed';
  if (line.stages.ready) return 'Ready';
  if (line.stages.tts) return 'Waiting on TTS';
  if (line.stages.writing) return 'Model is writing her first sentence';
  return line.info.frame ? 'Waiting on the image model' : 'Waiting on the model';
}

const STEP_LABELS = ['Model', 'Writing', 'TTS', 'Speaking'];

/** An overlay of what she's saying and responding to, and of the line she's preparing next. */
export function buildTurnMonitor(speech: SpeechPlayer, director: Director) {
  const nowImage = el('img', { className: 'monitor-image', alt: 'The frame behind what she is saying', hidden: true });
  const nowNote = el('p', { className: 'monitor-note', textContent: 'No reply yet.' });
  const headline = el('p', { className: 'monitor-headline', textContent: 'Idle' });
  const times = STEP_LABELS.map(() => el('span', { className: 'monitor-time' }));
  const steps = STEP_LABELS.map((label, i) => el('li', { className: 'monitor-step' }, el('span', { textContent: label }), times[i]));
  const nowWords = el('p', { className: 'monitor-reply' });

  const nextImage = el('img', { className: 'monitor-next-image', alt: 'The frame behind her next line', hidden: true });
  const nextStatus = el('p', { className: 'monitor-next-status', textContent: 'Up next: nothing yet' });
  const replaced = el('p', { className: 'monitor-note' });

  const overlay = el(
    'aside',
    { className: 'turn-monitor' },
    nowImage,
    nowNote,
    headline,
    el('ol', { className: 'monitor-steps' }, ...steps),
    nowWords,
    el('div', { className: 'monitor-next' }, nextImage, el('div', {}, nextStatus, replaced)),
  );
  overlay.setAttribute('aria-label', 'What she is responding to');

  let shownNow: PreparedLine | null = null;
  let shownNext: PreparedLine | null = null;

  const showImage = (image: HTMLImageElement, frame: string | null) => {
    image.hidden = frame === null;
    if (frame) image.src = frame;
  };

  const render = () => {
    const now = performance.now();
    const line = speech.line;
    if (line !== shownNow) {
      shownNow = line;
      if (line) showImage(nowImage, line.info.frame);
    }
    if (line) {
      const notes = [line.act && `Act: ${line.act}`, line.info.said && `You said: ${line.info.said}`, line.seen && `Saw: ${line.seen}`];
      nowNote.textContent = notes.filter(Boolean).join(' · ');
      nowNote.hidden = !nowNote.textContent;
      const speaking = speech.active;
      const values = stepTimes(line, now);
      const currentStep = values.reduce<number>((found, value, i) => (value === null ? found : i), 0);
      values.forEach((value, i) => {
        times[i].textContent = value === null ? '' : `${(value / 1000).toFixed(2)} s`;
        steps[i].classList.toggle('active', speaking && i === currentStep);
        steps[i].classList.toggle('done', value !== null && (i < currentStep || !speaking));
      });
      if (!speaking) headline.textContent = line.failed ? 'Failed' : 'Idle';
      else headline.textContent = line.stages.speaking ? 'Speaking' : waitingOn(line) === 'Ready' ? 'Speaking' : waitingOn(line);
      headline.classList.toggle('failed', line.failed);
      nowWords.textContent = line.heard.join('');
    }

    const next = director.nextLine;
    if (next !== shownNext) {
      shownNext = next;
      showImage(nextImage, next?.info.frame ?? null);
    }
    nextStatus.textContent = next ? `Up next: ${waitingOn(next)} (${next.info.reason}), ${((now - next.requestedAt) / 1000).toFixed(1)} s` : 'Up next: nothing yet';
    const notes = [
      director.running ? `Talking ${Math.round(director.talkShare * 100)}% of the last 90 s` : '',
      director.replacedCount > 0 ? `Replaced for fresher lines: ${director.replacedCount}` : '',
      director.declinedCount > 0 ? `Stayed quiet: ${director.declinedCount} (last saw: ${director.lastSeen ?? '?'})` : '',
    ];
    replaced.textContent = notes.filter(Boolean).join(' · ');
  };

  window.setInterval(() => {
    if (!overlay.hidden) render();
  }, TICK_MS);

  const toggle = el('input', { type: 'checkbox', checked: loadPreference() });
  const applyToggle = () => {
    overlay.hidden = !toggle.checked;
    savePreference(toggle.checked);
  };
  toggle.onchange = applyToggle;
  document.body.append(overlay);
  applyToggle();

  return { toggle: el('label', { className: 'check' }, toggle, 'Show what she is responding to') };
}
