import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { Preview } from './Preview';
import { createRef } from 'react';

describe('Preview', () => {
  it('renders a heading from markdown', () => {
    const ref = createRef<HTMLDivElement>();
    const { container } = render(<Preview ref={ref} markdown="# Hello" />);
    expect(container.querySelector('h1')?.textContent).toBe('Hello');
  });

  it('renders bold text from markdown', () => {
    const ref = createRef<HTMLDivElement>();
    const { container } = render(<Preview ref={ref} markdown="**bold**" />);
    expect(container.querySelector('strong')).not.toBeNull();
  });

  it('renders an unordered list from markdown', () => {
    const ref = createRef<HTMLDivElement>();
    const { container } = render(
      <Preview ref={ref} markdown={'- item one\n- item two'} />,
    );
    expect(container.querySelectorAll('li')).toHaveLength(2);
  });

  it('renders a code block from markdown', () => {
    const ref = createRef<HTMLDivElement>();
    const { container } = render(
      <Preview ref={ref} markdown={'```\nconsole.log(1)\n```'} />,
    );
    expect(container.querySelector('code')).not.toBeNull();
  });

  it('strips <script> tags via DOMPurify', () => {
    const ref = createRef<HTMLDivElement>();
    const { container } = render(
      <Preview
        ref={ref}
        markdown={'<script>alert("xss")</script> safe text'}
      />,
    );
    expect(container.querySelector('script')).toBeNull();
    expect(container.textContent).toContain('safe text');
  });

  it('renders an empty preview for empty markdown', () => {
    const ref = createRef<HTMLDivElement>();
    const { container } = render(<Preview ref={ref} markdown="" />);
    const content = container.querySelector('.preview-content');
    expect(content?.innerHTML).toBe('');
  });

  it('exposes the ref on the preview-content div', () => {
    const ref = createRef<HTMLDivElement>();
    render(<Preview ref={ref} markdown="# Test" />);
    expect(ref.current).not.toBeNull();
    expect(ref.current?.classList.contains('preview-content')).toBe(true);
  });
});
