import { marked } from 'marked';
import DOMPurify from 'dompurify';

/**
 * Parse a markdown string into sanitized HTML.
 *
 * The pipeline is:
 *   1. marked.parse() – converts markdown to HTML
 *   2. DOMPurify.sanitize() – strips XSS payloads before DOM injection
 *
 * Returns an empty string for empty / whitespace-only input without errors.
 */
export function parseMarkdown(raw: string): string {
  if (!raw.trim()) return '';
  const html = marked.parse(raw) as string;
  return DOMPurify.sanitize(html);
}
