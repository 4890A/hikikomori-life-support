import { el, section } from '../dom';

const API = '/speech/companion';

interface Card {
  name: string;
  personality: string;
  speech_style: string;
  scenario: string;
  likes: string[];
  dislikes: string[];
  rules: string[];
  examples: string[];
  screen_instruction: string;
}

interface Fact {
  text: string;
  source: 'you' | 'said' | 'guess';
}

interface MemoryView {
  facts: Fact[];
  her: string[];
  episodes: { title: string; summary: string; when: string }[];
  today: string;
}

const SOURCE_LABELS: Record<string, string> = { you: 'You wrote', said: 'You said', guess: 'Her guess' };

const TEXT_FIELDS = [
  ['name', 'Name', 1],
  ['personality', 'Personality', 4],
  ['speech_style', 'Speaking style', 3],
  ['scenario', 'Situation', 3],
  ['screen_instruction', 'When reacting to the screen', 2],
] as const;
const LIST_FIELDS = [
  ['likes', 'Likes (one per line)', 3],
  ['dislikes', 'Dislikes (one per line)', 2],
  ['rules', 'Rules (one per line)', 6],
  ['examples', 'Example lines (one per line)', 5],
] as const;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, init);
  if (!response.ok) throw new Error(`${response.status}: ${(await response.text()).slice(0, 200)}`);
  return response.json() as Promise<T>;
}

/** The character card editor, her memory and a preview of the full prompt. */
export function buildCharacterPanel() {
  const fields = new Map<string, HTMLTextAreaElement>();
  const field = (key: string, label: string, rows: number) => {
    const input = el('textarea', { id: `card-${key}`, rows });
    fields.set(key, input);
    return el('label', { className: 'field' }, label, input);
  };
  const status = el('p', { className: 'hint' });
  const show = (message: string) => {
    status.textContent = message;
  };

  const fill = (card: Card) => {
    for (const [key] of TEXT_FIELDS) fields.get(key)!.value = card[key];
    for (const [key] of LIST_FIELDS) fields.get(key)!.value = card[key].join('\n');
  };
  const read = () => {
    const card: Record<string, unknown> = {};
    for (const [key] of TEXT_FIELDS) card[key] = fields.get(key)!.value.trim();
    for (const [key] of LIST_FIELDS) {
      card[key] = fields.get(key)!.value.split('\n').map((line) => line.trim()).filter(Boolean);
    }
    return card;
  };

  const prompt = el('pre', { className: 'prompt-preview' });
  const refreshPrompt = async () => {
    const { system, turn } = await request<{ system: string; turn: string }>('/prompt');
    prompt.textContent = `${system}\n\n---- Added to each turn ----\n\n${turn}`;
  };

  const facts = el('ul', { className: 'facts' });
  const her = el('ul', { className: 'facts' });
  const episodes = el('ul', { className: 'facts' });
  const today = el('p', { className: 'hint' });
  const json = (method: string, body: unknown): RequestInit => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const forget = (path: string) =>
    el('button', {
      textContent: '×',
      title: 'Forget this',
      onclick: () => void change(() => request<MemoryView>(path, { method: 'DELETE' }).then(showMemory), 'Forgotten.'),
    });
  // Click a fact to rewrite it. Your version is kept as you wrote it.
  const editable = (fact: Fact, index: number) => {
    const text = el('span', { className: 'fact-text', textContent: fact.text, title: 'Click to edit' });
    text.onclick = () => {
      const input = el('input', { type: 'text', value: fact.text, maxLength: 80 });
      const save = () => {
        const value = input.value.trim();
        if (!value || value === fact.text) return void refreshMemory();
        void change(() => request<MemoryView>(`/memory/facts/${index}`, json('PUT', { text: value })).then(showMemory), 'Saved. She keeps it as you wrote it.');
      };
      input.onkeydown = (e) => {
        if (e.key === 'Enter') save();
        if (e.key === 'Escape') void refreshMemory();
      };
      input.onblur = save;
      text.replaceWith(input);
      input.focus();
    };
    return text;
  };
  const showMemory = (memory: MemoryView) => {
    facts.replaceChildren(
      ...memory.facts.map((fact, index) =>
        el('li', {}, el('span', { className: 'fact-source', textContent: SOURCE_LABELS[fact.source] ?? '' }), editable(fact, index), forget(`/memory/facts/${index}`)),
      ),
    );
    if (memory.facts.length === 0) facts.append(el('li', { className: 'hint', textContent: 'Nothing yet. Tell her about yourself, or add something below.' }));
    her.replaceChildren(...memory.her.map((bit, index) => el('li', {}, bit, forget(`/memory/her/${index}`))));
    if (memory.her.length === 0) her.append(el('li', { className: 'hint', textContent: 'Nothing yet.' }));
    episodes.replaceChildren(
      ...memory.episodes
        .map((episode, index) => el('li', { title: episode.summary }, `${episode.when}: ${episode.title}`, forget(`/memory/episodes/${index}`)))
        .reverse(),
    );
    if (memory.episodes.length === 0) episodes.append(el('li', { className: 'hint', textContent: 'None yet. A session becomes one when you stop her.' }));
    today.textContent = memory.today ? `Today so far: ${memory.today}` : '';
  };
  const refreshMemory = async () => showMemory(await request<MemoryView>('/memory'));
  const newFact = el('input', { type: 'text', placeholder: 'Add something about you (Enter)', maxLength: 80 });
  newFact.onkeydown = (e) => {
    if (e.key !== 'Enter' || !newFact.value.trim()) return;
    const text = newFact.value.trim();
    newFact.value = '';
    void change(() => request<MemoryView>('/memory/facts', json('POST', { text })).then(showMemory), 'Added.');
  };

  const change = async (action: () => Promise<unknown>, done: string) => {
    try {
      await action();
      await refreshPrompt();
      show(done);
    } catch (err) {
      show(`Couldn't do that: ${err instanceof Error ? err.message : err}`);
    }
  };

  const saveButton = el('button', {
    textContent: 'Save character',
    onclick: () =>
      void change(
        () =>
          request<Card>('/character', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(read()),
          }).then(fill),
        'Saved. It applies from her next line.',
      ),
  });
  const resetButton = el('button', {
    textContent: 'Reset to default',
    onclick: () => void change(() => request<Card>('/character', { method: 'DELETE' }).then(fill), 'Back to the default character.'),
  });

  // Asks twice in the panel itself, because this can't be undone.
  const clearButton = el('button', { textContent: 'Clear all memory' });
  let armed = false;
  clearButton.onclick = () => {
    if (!armed) {
      armed = true;
      clearButton.textContent = 'Click again to clear';
      window.setTimeout(() => {
        armed = false;
        clearButton.textContent = 'Clear all memory';
      }, 4000);
      return;
    }
    armed = false;
    clearButton.textContent = 'Clear all memory';
    void change(() => request<MemoryView>('/memory', { method: 'DELETE' }).then(showMemory), 'Memory cleared.');
  };

  const details = (title: string, onOpen: () => void, ...children: Node[]) => {
    const box = el('details', {}, el('summary', { textContent: title }), ...children);
    box.ontoggle = () => {
      if (box.open) onOpen();
    };
    return box;
  };

  const load = async () => {
    try {
      fill(await request<Card>('/character'));
      await Promise.all([refreshMemory(), refreshPrompt()]);
      show('');
    } catch {
      show('Character not loaded. Are the speech bridge scripts running?');
    }
  };
  void load();

  return section(
    'Character',
    details(
      'Edit character',
      () => void load(),
      ...TEXT_FIELDS.map(([key, label, rows]) => field(key, label, rows)),
      ...LIST_FIELDS.map(([key, label, rows]) => field(key, label, rows)),
      el('div', { className: 'row' }, saveButton, resetButton),
    ),
    details(
      'Memory',
      () => void refreshMemory(),
      el('p', { className: 'field-label', textContent: 'About you (click to edit)' }),
      facts,
      newFact,
      el('p', { className: 'field-label', textContent: 'Past sessions' }),
      episodes,
      today,
      el('p', { className: 'field-label', textContent: 'Things she said about herself' }),
      her,
      el('div', { className: 'row' }, clearButton),
    ),
    details('Full prompt', () => void refreshPrompt(), prompt),
    status,
  );
}
