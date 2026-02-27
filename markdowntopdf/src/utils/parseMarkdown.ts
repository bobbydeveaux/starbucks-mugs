import { marked } from 'marked';
import DOMPurify from 'dompurify';

/**
 * Converts raw markdown to sanitized HTML.
 * Uses marked.js for parsing and DOMPurify for XSS prevention.
 */
export function parseMarkdown(raw: string): string {
  if (!raw) return '';
  const html = marked.parse(raw) as string;
  return DOMPurify.sanitize(html);
}
