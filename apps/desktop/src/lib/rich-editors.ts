import type { Editor } from '@tiptap/core';

const editors = new WeakMap<HTMLElement, Editor>();
export const editorSelection = new EventTarget();
export function registerRichEditor(editor: Editor) {
  const element = editor.view.dom;
  editors.set(element, editor);
  element.dataset.islandEditor = '';
  const notify = () => editorSelection.dispatchEvent(new Event('change'));
  editor.on('transaction', notify);
  return () => {
    editor.off('transaction', notify);
    editors.delete(element);
    notify();
  };
}
export function selectedRichEditor(node: Node | null): Editor | undefined {
  const element = node instanceof HTMLElement ? node : node?.parentElement;
  const root = element?.closest<HTMLElement>('[data-island-editor]');
  return root ? editors.get(root) : undefined;
}
