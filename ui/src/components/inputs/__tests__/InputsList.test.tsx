/**
 * AD-926: InputsList — read-only task-room Inputs pane.
 *
 * Presentational component: renders one download/open row per input
 * (linking to the existing GET /api/chat/attachments/{content_hash}),
 * an empty state, and stroke-SVG icons only (HXI Design Principle #3 —
 * no emoji).
 */
import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';

import { InputsList } from '../InputsList';
import type { TaskInput } from '../inputsApi';

const EMOJI_RE = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{1F600}-\u{1F64F}]/u;

afterEach(() => {
  cleanup();
});

const TWO_INPUTS: TaskInput[] = [
  {
    content_hash: 'aaa111',
    mime: 'image/png',
    filename: 'diagram.png',
    size: 2048,
    source: 'task',
  },
  {
    content_hash: 'bbb222',
    mime: 'text/plain',
    filename: null,
    size: null,
    source: 'message',
  },
];

describe('InputsList (AD-926)', () => {
  it('renders one row per content_hash linking to the attachment endpoint', () => {
    render(<InputsList inputs={TWO_INPUTS} />);
    expect(screen.getByTestId('inputs-list')).toBeTruthy();
    const rowA = screen.getByTestId('input-row-aaa111');
    const rowB = screen.getByTestId('input-row-bbb222');
    expect(rowA.getAttribute('href')).toBe('/api/chat/attachments/aaa111');
    expect(rowB.getAttribute('href')).toBe('/api/chat/attachments/bbb222');
    // named input shows its filename text
    expect(rowA.textContent).toContain('diagram.png');
  });

  it('shows the empty state when inputs is empty', () => {
    render(<InputsList inputs={[]} />);
    expect(screen.getByTestId('inputs-list-empty').textContent).toBe(
      'No inputs yet.',
    );
  });

  it('renders no emoji (HXI Design Principle #3 — stroke-SVG icons only)', () => {
    const { container } = render(<InputsList inputs={TWO_INPUTS} />);
    expect(container.textContent || '').not.toMatch(EMOJI_RE);
  });
});
