import { describe, it, expect } from 'vitest';
import { parseMarkdown } from './parseMarkdown';

describe('parseMarkdown', () => {
  it('converts a heading to an <h1> element', () => {
    const result = parseMarkdown('# Hello World');
    expect(result).toContain('<h1>');
    expect(result).toContain('Hello World');
  });

  it('converts bold markdown to <strong>', () => {
    const result = parseMarkdown('**bold text**');
    expect(result).toContain('<strong>');
    expect(result).toContain('bold text');
  });

  it('converts italic markdown to <em>', () => {
    const result = parseMarkdown('_italic text_');
    expect(result).toContain('<em>');
    expect(result).toContain('italic text');
  });

  it('converts an unordered list to <ul>/<li> elements', () => {
    const result = parseMarkdown('- item one\n- item two');
    expect(result).toContain('<ul>');
    expect(result).toContain('<li>');
    expect(result).toContain('item one');
  });

  it('converts a code block to <code>', () => {
    const result = parseMarkdown('`console.log("hi")`');
    expect(result).toContain('<code>');
  });

  it('strips <script> XSS payloads', () => {
    const result = parseMarkdown('<script>alert("xss")</script>');
    expect(result).not.toContain('<script>');
    expect(result).not.toContain('alert');
  });

  it('strips inline event handler XSS payloads', () => {
    const result = parseMarkdown('[click me](javascript:alert(1))');
    expect(result).not.toContain('javascript:');
  });

  it('strips onerror attribute XSS payloads', () => {
    const result = parseMarkdown('<img src="x" onerror="alert(1)">');
    expect(result).not.toContain('onerror');
  });

  it('returns empty string for empty input', () => {
    expect(parseMarkdown('')).toBe('');
  });

  it('does not throw on whitespace-only input', () => {
    expect(() => parseMarkdown('   ')).not.toThrow();
  });
});
