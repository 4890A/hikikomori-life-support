export const el = <K extends keyof HTMLElementTagNameMap>(tag: K, props: Record<string, unknown> = {}, ...children: (Node | string)[]): HTMLElementTagNameMap[K] => {
  const node = Object.assign(document.createElement(tag), props);
  node.append(...children);
  return node;
};

export const section = (title: string, ...children: Node[]) => el('section', {}, el('h2', { textContent: title }), ...children);
