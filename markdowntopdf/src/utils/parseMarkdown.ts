import { marked } from 'marked';
import DOMPurify from 'dompurify';

/**
 * Converts a markdown string to sanitized HTML.
 *
 * Chains marked.parse() for markdown-to-HTML conversion with
 * DOMPurify.sanitize() to strip any XSS payloads before the
 * result is injected into the DOM.
 *
 * @param raw - Raw markdown input string
 * @returns Sanitized HTML string safe for dangerouslySetInnerHTML
 */
export function parseMarkdown(raw: string): string {
  if (!raw) return '';
  const html = marked.parse(raw, { async: false });
  return DOMPurify.sanitize(html);
}
