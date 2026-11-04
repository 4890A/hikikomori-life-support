import { ACTIONS, type ActionName, type Animator } from './anim/animator';
import { EMOTIONS } from './anim/emotions';
import type { SpeechPlayer } from './anim/speech';
import { CHATTINESS, type Chattiness, type Director } from './companion/director';
import type { ViewName } from './main';

const el = <K extends keyof HTMLElementTagNameMap>(tag: K, props: Record<string, unknown> = {}, ...children: (Node | string)[]): HTMLElementTagNameMap[K] => {
  const node = Object.assign(document.createElement(tag), props);
  node.append(...children);
  return node;
};

const section = (title: string, ...children: Node[]) => el('section', {}, el('h2', { textContent: title }), ...children);

export function buildPanel(root: HTMLElement, animator: Animator, speech: SpeechPlayer, director: Director, setView: (v: ViewName) => void) {
  // Emotions, with number-key shortcuts.
  const names = Object.keys(EMOTIONS);
  const buttons = new Map<string, HTMLButtonElement>();
  const grid = el('div', { className: 'grid' });
  names.forEach((name, i) => {
    const key = i < 9 ? String(i + 1) : i === 9 ? '0' : '';
    const b = el('button', { onclick: () => animator.setEmotion(name), title: key ? `Key ${key}` : '' }, EMOTIONS[name].label);
    if (key) b.append(el('kbd', { textContent: key }));
    buttons.set(name, b);
    grid.append(b);
  });
  const markActive = (name: string) => buttons.forEach((b, n) => b.classList.toggle('active', n === name));
  animator.onEmotionChange = markActive;
  markActive(animator.currentEmotion);
  window.addEventListener('keydown', (e) => {
    if ((e.target as HTMLElement).closest('textarea, input, select')) return;
    const idx = e.key === '0' ? 9 : Number(e.key) - 1;
    if (idx >= 0 && idx < names.length && /^[0-9]$/.test(e.key)) animator.setEmotion(names[idx]);
    if (e.key.toLowerCase() === 'g') animator.playAction('six_seven');
  });

  // One-shot gestures, played over the current emotion.
  const actions = el(
    'div',
    { className: 'row' },
    ...(Object.entries(ACTIONS) as [ActionName, string][]).map(([name, label]) => {
      const b = el('button', { onclick: () => animator.playAction(name), title: name === 'six_seven' ? 'Key G' : '' }, label);
      if (name === 'six_seven') b.append(el('kbd', { textContent: 'G' }));
      return b;
    }),
  );

  // Companion: she watches a shared game window and answers what you type.
  const companionStatus = el('p', { className: 'hint' });
  const companionTiming = el('p', { className: 'hint' });
  const companionLog = el('ul', { className: 'cues' });
  const say = el('input', { type: 'text', placeholder: '話しかける… (Enter)' });
  const chattiness = el('select', { title: 'How often she comments' });
  chattiness.append(...Object.keys(CHATTINESS).map((level) => el('option', { value: level, textContent: level[0].toUpperCase() + level.slice(1) })));
  try {
    const saved = localStorage.getItem('companion-chattiness');
    if (saved && saved in CHATTINESS) director.chattiness = saved as Chattiness;
  } catch {
    // Storage can be blocked; the default still works.
  }
  chattiness.value = director.chattiness;
  chattiness.onchange = () => {
    director.chattiness = chattiness.value as Chattiness;
    try {
      localStorage.setItem('companion-chattiness', chattiness.value);
    } catch {
      // Only the choice isn't remembered.
    }
  };
  const startCompanion = el('button', { textContent: '▶ Start Companion' });
  let turns = 0;
  let spent = 0;
  let reason = '';
  let face = '';
  const logLine = (line: string) => {
    companionLog.prepend(el('li', { textContent: line }));
    while (companionLog.children.length > 5) companionLog.lastElementChild?.remove();
  };
  const showTiming = (extra = '') => {
    companionTiming.textContent = `${reason}${face}${extra}`;
  };
  director.onTurn = (why) => {
    reason = why;
    face = '';
    turns += 1;
    showTiming();
  };
  director.onStopped = () => {
    startCompanion.textContent = '▶ Start Companion';
    startCompanion.classList.remove('active');
    companionStatus.textContent = '';
  };
  speech.onFace = (emoji, seconds) => {
    face = ` · ${emoji} ${seconds.toFixed(2)}s`;
    showTiming();
  };
  speech.onFirstAudio = (seconds) => showTiming(` · audio ${seconds.toFixed(2)}s`);
  speech.onTrace = (trace) => {
    spent += trace.cost ?? 0;
    companionStatus.textContent = `Watching · ${turns} turns · $${spent.toFixed(4)}`;
  };
  startCompanion.onclick = async () => {
    if (director.running) {
      director.stop();
      return;
    }
    try {
      await director.start();
      startCompanion.textContent = '■ Stop Companion';
      startCompanion.classList.add('active');
      companionStatus.textContent = 'Watching';
    } catch (err) {
      // Closing the browser's window picker also lands here.
      companionStatus.textContent = `Not started: ${err instanceof Error ? err.message : err}`;
    }
  };
  say.onkeydown = (e) => {
    if (e.key !== 'Enter' || e.isComposing || !say.value.trim()) return;
    logLine(`you: ${say.value}`);
    void director.say(say.value);
    say.value = '';
  };
  const companion = section(
    'Companion',
    el('div', { className: 'row' }, startCompanion),
    el('label', { className: 'file' }, 'How often she comments ', chattiness),
    say,
    el('p', { className: 'hint', textContent: 'Share only the window you want her to see: frames go to OpenRouter.' }),
    companionStatus,
    companionTiming,
    companionLog,
  );

  // Irodori-TTS speech: emoji in the text drive both the voice and timed expressions.
  const voiceText = el('textarea', {
    rows: 4,
    value: 'えへへ🤭、今日はすごく楽しかったよ😊。でもね、ちょっと恥ずかしいことがあって🫣…😮‍💨まぁ、いっか。えっ😲、本当に？やったー😆！',
  });
  const voiceStatus = el('p', { className: 'hint' });
  const voiceCues = el('ul', { className: 'cues' });
  speech.onStatus = (message) => {
    voiceStatus.textContent = message;
    if (message.startsWith('Speech failed')) logLine(message);
  };
  speech.onSegment = (segment) => {
    if (segment.ignored_emoji.length > 0) console.info('voice-only emoji (no expression):', segment.ignored_emoji.join(' '));
    if (segment.count === null) logLine(segment.text);
  };
  speech.onCue = (cue) => {
    voiceCues.prepend(el('li', { textContent: `${cue.emoji} → ${EMOTIONS[cue.emotion]?.label ?? cue.emotion} (${(cue.end - cue.start).toFixed(1)}s)` }));
    while (voiceCues.children.length > 6) voiceCues.lastElementChild?.remove();
  };
  const palette = el('div', { className: 'emoji-palette' });
  void fetch('/speech/emoji')
    .then((r) => r.json())
    .then((map: Record<string, string>) => {
      for (const [emoji, emotion] of Object.entries(map)) {
        palette.append(
          el('button', {
            textContent: emoji,
            title: EMOTIONS[emotion]?.label ?? emotion,
            onclick: () => voiceText.setRangeText(emoji, voiceText.selectionStart, voiceText.selectionEnd, 'end'),
          }),
        );
      }
    })
    .catch(() => {
      voiceStatus.textContent = 'Speech bridge not reachable. Run scripts/start-tts.ps1 and scripts/start-speech.ps1.';
    });
  const voice = section(
    'Voice (Irodori-TTS)',
    voiceText,
    palette,
    el(
      'div',
      { className: 'row' },
      el('button', {
        textContent: '🔊 Speak with emotions',
        onclick: () => {
          voiceCues.replaceChildren();
          void speech.speak(voiceText.value);
        },
      }),
      el('button', { textContent: '■ Stop', onclick: () => speech.stop() }),
    ),
    voiceStatus,
    voiceCues,
  );

  // Talking.
  const text = el('textarea', {
    rows: 3,
    value: "Hi there! I'm DeepSeek-chan. Hmm, what should we think about today?",
  });
  const voices = el('select');
  const loadVoices = () => {
    const list = window.speechSynthesis?.getVoices() ?? [];
    voices.replaceChildren(el('option', { value: '', textContent: 'Default voice' }), ...list.map((v, i) => el('option', { value: String(i), textContent: `${v.name} (${v.lang})` })));
  };
  loadVoices();
  window.speechSynthesis?.addEventListener('voiceschanged', loadVoices);
  const pickedVoice = () => (voices.value ? window.speechSynthesis.getVoices()[Number(voices.value)] : null);
  const mic = el('button', { textContent: '🎤 Mic lip-sync' });
  let micOn = false;
  mic.onclick = async () => {
    if (micOn) {
      animator.talk.stop();
      micOn = false;
    } else {
      try {
        await animator.talk.useMicrophone();
        micOn = true;
      } catch (err) {
        alert(`Microphone unavailable: ${err}`);
      }
    }
    mic.classList.toggle('active', micOn);
  };
  const file = el('input', { type: 'file', accept: 'audio/*' });
  file.onchange = () => {
    const f = file.files?.[0];
    if (f) void animator.talk.playAudio(URL.createObjectURL(f));
  };
  const talk = section(
    'Talk',
    text,
    el(
      'div',
      { className: 'row' },
      el('button', { textContent: '🔊 Speak', onclick: () => animator.talk.speak(text.value, { voice: pickedVoice() }) }),
      el('button', { textContent: '👄 Lip-flap only', onclick: () => animator.talk.babble(text.value) }),
      el('button', { textContent: '■ Stop', onclick: () => { animator.talk.stop(); micOn = false; mic.classList.remove('active'); } }),
    ),
    voices,
    el('div', { className: 'row' }, mic),
    el('label', { className: 'file' }, 'Lip-sync an audio file ', file),
  );

  // Behaviour switches and outfit toggles.
  const check = (label: string, get: () => boolean, set: (v: boolean) => void) => {
    const input = el('input', { type: 'checkbox', checked: get() });
    input.onchange = () => set(input.checked);
    return el('label', { className: 'check' }, input, label);
  };
  const toggle = (label: string, id: string, on: number, off: number) =>
    check(label, () => (animator.toggles[id] ?? off) === on, (v) => (animator.toggles[id] = v ? on : off));
  const behaviour = section(
    'Behaviour',
    check('Follow mouse', () => animator.options.followPointer, (v) => (animator.options.followPointer = v)),
    check('Idle motion', () => animator.options.idle, (v) => (animator.options.idle = v)),
    check('Blink', () => animator.options.blink, (v) => (animator.options.blink = v)),
  );
  const outfit = section(
    'Outfit',
    toggle('Short skirt', 'Clothes1', 1, 0),
    toggle('Glasses', 'key11', 1, 0),
    toggle('Monocle', 'key12', 1, 0),
    toggle('Fang', 'key9', 1, 0),
  );
  const view = section(
    'View',
    el(
      'div',
      { className: 'row' },
      ...(['full', 'upper', 'face'] as ViewName[]).map((v) => el('button', { textContent: v[0].toUpperCase() + v.slice(1), onclick: () => setView(v) })),
    ),
  );

  const toggleBtn = el('button', { className: 'collapse', textContent: '☰', title: 'Show/hide panel', onclick: () => root.classList.toggle('collapsed') });
  root.append(toggleBtn, companion, voice, section('Emotion', grid), section('Gesture', actions), talk, behaviour, outfit, view, el('p', { className: 'hint', textContent: 'Click her head for a pat, her body for a poke.' }));
}
