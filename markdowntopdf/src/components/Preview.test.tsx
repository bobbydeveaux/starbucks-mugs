import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Preview } from './Preview';

// Mock parseMarkdown so Preview tests are unit-scoped
vi.mock('../utils/parseMarkdown', () => ({
  parseMarkdown: (raw: string) => {
    if (!raw.trim()) return '';
    if (raw.startsWith('# ')) return `<h1>${raw.slice(2).trim()}</h1>`;
    if (raw.includes('<script>')) return ''; // simulate XSS stripping
    return `<p>${raw}</p>`;
  },
}));

describe('Preview', () => {
  beforeEach(() => {
    // Clear any leftover DOM between tests
    document.body.innerHTML = '';
  });

  it('renders the "Preview" pane header', () => {
    render(<Preview markdown="" />);
    expect(screen.getByText('Preview')).toBeInTheDocument();
  });

  it('renders sanitized HTML from a heading markdown string', () => {
    render(<Preview markdown="# Hello World" />);
    const content = document.querySelector('.preview-content');
    expect(content).not.toBeNull();
    expect(content?.innerHTML).toBe('<h1>Hello World</h1>');
  });

  it('renders a paragraph for plain text markdown', () => {
    render(<Preview markdown="some text" />);
    const content = document.querySelector('.preview-content');
    expect(content?.innerHTML).toBe('<p>some text</p>');
  });

  it('renders nothing for an empty string', () => {
    render(<Preview markdown="" />);
    const content = document.querySelector('.preview-content');
    expect(content?.innerHTML).toBe('');
  });

  it('renders nothing for whitespace-only input', () => {
    render(<Preview markdown="   " />);
    const content = document.querySelector('.preview-content');
    expect(content?.innerHTML).toBe('');
  });

  it('strips XSS payloads (script tags are removed)', () => {
    render(<Preview markdown="<script>alert('xss')</script>" />);
    const content = document.querySelector('.preview-content');
    expect(content?.innerHTML).toBe('');
  });

  it('forwards its ref to the preview-content div', () => {
    const ref = React.createRef<HTMLDivElement>();
    render(<Preview ref={ref} markdown="# Test" />);
    expect(ref.current).not.toBeNull();
    expect(ref.current?.classList.contains('preview-content')).toBe(true);
  });

  it('updates rendered HTML when the markdown prop changes', () => {
    const { rerender } = render(<Preview markdown="# First" />);
    expect(document.querySelector('.preview-content')?.innerHTML).toBe(
      '<h1>First</h1>',
    );

    rerender(<Preview markdown="# Second" />);
    expect(document.querySelector('.preview-content')?.innerHTML).toBe(
      '<h1>Second</h1>',
    );
  });
});
