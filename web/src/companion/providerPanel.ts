import type { TurnTrace } from '../anim/speech';
import { el } from '../dom';

const URL_PROVIDERS = '/speech/companion/providers';
const POLL_MS = 500;

interface ProviderRow {
  provider: string;
  p50_ms: number;
  p90_ms: number;
  tokens_per_second: number;
  price: number;
}

interface ProviderStatus {
  checking: boolean;
  checked_at: number | null;
  error: string | null;
  main_model: string;
  fallback_model: string;
  models: Record<string, ProviderRow[]>;
}

const shortName = (model: string) => model.split('/').pop() ?? model;

/** Shows which provider OpenRouter's figures picked, and which one actually answered her last line. */
export function buildProviderPanel() {
  const current = el('p', { className: 'hint', textContent: 'Checking providers…' });
  const last = el('p', { className: 'hint' });
  const list = el('ul', { className: 'cues' });
  const recheck = el('button', { textContent: 'Check again' });
  let poll = 0;

  const show = (status: ProviderStatus) => {
    const rows = status.models[status.main_model] ?? [];
    recheck.disabled = status.checking;
    const model = shortName(status.main_model);
    if (rows[0]) current.textContent = `Vision: ${model} via ${rows[0].provider}. OpenRouter reports ${rows[0].p50_ms} ms typical, ${rows[0].p90_ms} ms slow.`;
    else if (status.error) current.textContent = `Vision: ${model}, using the default providers. Couldn't check: ${status.error}`;
    else current.textContent = `Vision: ${model}, using the default providers.`;
    list.replaceChildren(
      ...rows.map((r) => el('li', { textContent: `${r.provider}: ${r.p50_ms}/${r.p90_ms} ms, ${r.tokens_per_second} tok/s, $${r.price.toFixed(2)}/M` })),
    );
  };

  const refresh = async () => {
    window.clearTimeout(poll);
    try {
      const response = await fetch(URL_PROVIDERS);
      if (!response.ok) throw new Error(String(response.status));
      const status = (await response.json()) as ProviderStatus;
      show(status);
      // The first check starts with the bridge, which can take a moment to come up.
      if (status.checking || (!status.checked_at && !status.error)) poll = window.setTimeout(() => void refresh(), POLL_MS);
    } catch {
      current.textContent = 'Provider status unavailable. Is the speech bridge running?';
    }
  };

  recheck.onclick = () => {
    recheck.disabled = true;
    void fetch(`${URL_PROVIDERS}/check`, { method: 'POST' }).then(() => refresh());
  };
  void refresh();

  return {
    element: el(
      'div',
      {},
      current,
      last,
      el('details', {}, el('summary', { textContent: 'Top providers (typical/slow)' }), list, el('div', { className: 'row' }, recheck)),
    ),
    /** What actually answered her latest line, measured from here. It may be another provider or the fallback. */
    showTrace(trace: TurnTrace) {
      if (trace.model) last.textContent = `Last reply: ${shortName(trace.model)} via ${trace.provider ?? 'unknown'}${trace.first_token ? `, ${trace.first_token.toFixed(2)} s to first word` : ''}`;
    },
  };
}
