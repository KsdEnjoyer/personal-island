import { generateHTML, generateText, type JSONContent } from '@tiptap/core';
import StarterKit from '@tiptap/starter-kit';
import Highlight from '@tiptap/extension-highlight';
import TaskList from '@tiptap/extension-task-list';
import TaskItem from '@tiptap/extension-task-item';
import { Markdown, MarkdownManager } from '@tiptap/markdown';

export const richExtensions = () => [StarterKit.configure({link:false,trailingNode:false}),Highlight.configure({multicolor:true}),TaskList,TaskItem.configure({nested:true})];
export const markdownExtensions = () => [...richExtensions(),Markdown];
const manager = new MarkdownManager({extensions:richExtensions()});
const cache = new Map<string,{document:JSONContent;html:string;text:string}>();
export function richText(value: string) {
  const saved = cache.get(value);
  if (saved) return saved;
  const document = manager.parse(value);
  // Only the registered editor schema produces HTML. Raw Markdown/HTML is
  // never inserted into the app; scripts, images and links aren't in it.
  const result = {document,html:generateHTML(document,richExtensions()),text:generateText(document,richExtensions())};
  if (cache.size >= 64) cache.delete(cache.keys().next().value!);
  cache.set(value,result);
  return result;
}
