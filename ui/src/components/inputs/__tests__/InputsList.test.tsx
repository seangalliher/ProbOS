/**
 * AD-926: InputsList — read-only task-room Inputs pane.
 *
 * Presentational component: renders one download/open row per input
 * (linking to the existing GET /api/chat/attachments/{content_hash}),
 * an empty state, and stroke-SVG icons only (HXI Design Principle #3 —
 * no emoji).
 */
import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';

import { InputsList } from '../InputsList';
import { fetchThreadInputs, type TaskInput } from '../inputsApi';

const EMOJI_RE = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{1F600}-\u{1F64F}]/u;

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const TWO_INPUTS: TaskInput[] = [
  {
    content_hash: 'aaa111',
    mime: 'image/png',
    filename: 'diagram.png',
    size: 2048,
    source: 'task',
    available: true,
  },
  {
    content_hash: 'bbb222',
    mime: 'text/plain',
    filename: null,
    size: null,
    source: 'message',
    available: true,
  },
];

describe('InputsList (AD-926)', () => {
  it.each(['loading', 'error'] as const)('does not show empty success during %s', status => {
    render(<InputsList inputs={[]} status={status} />);
    expect(screen.queryByTestId('inputs-list-empty')).toBeNull();
    expect(screen.getByRole(status === 'error' ? 'alert' : 'status')).toHaveTextContent(
      status === 'error' ? 'Inputs unavailable.' : 'Checking inputs...',
    );
  });

  it.each([
    { available: true, status: 'ready' as const, label: 'Ready', enabled: true },
    { available: false, status: 'ready' as const, label: 'Unavailable', enabled: false },
    { available: undefined, status: 'ready' as const, label: 'Checking', enabled: false },
    { available: true, status: 'loading' as const, label: 'Checking', enabled: false },
    { available: true, status: 'error' as const, label: 'Unavailable', enabled: false },
  ])('renders $label accurately for $status / $available', ({ available, status, label, enabled }) => {
    render(<InputsList inputs={[{ ...TWO_INPUTS[0], available }]} status={status} />);
    const row = screen.getByTestId('input-row-aaa111');
    expect(row).toHaveTextContent('diagram.png');
    expect(row).toHaveTextContent('2.0 KB');
    expect(row).toHaveTextContent(label);
    expect(row.hasAttribute('href')).toBe(enabled);
    expect(row).toHaveAttribute('aria-disabled', String(!enabled));
  });

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

describe('fetchThreadInputs contract', () => {
  const row: TaskInput = { ...TWO_INPUTS[0], content_hash: 'a'.repeat(64) };
  const envelope = { thread_id: 'room/1', task_id: null, inputs: [row] };

  it.each([[], [row], [{ ...row, available: undefined }]].map(inputs => ({ inputs })))('accepts empty, ready and legacy inputs: $inputs', async ({ inputs }) => {
    const request = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ...envelope, inputs })));
    vi.stubGlobal('fetch', request);
    expect(await fetchThreadInputs('room/1')).toEqual(inputs);
    expect(request).toHaveBeenCalledWith('/api/threads/room%2F1/inputs');
  });

  it('rejects a non-OK initial response instead of returning an empty list', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('unavailable', { status: 503 })));
    await expect(fetchThreadInputs('room/1')).rejects.toThrow('503');
  });

  it.each([
    null, [], {}, { ...envelope, thread_id: 'other-room' },
    { ...envelope, inputs: null }, { ...envelope, task_id: 2 },
    ...[null, {}, { ...row, content_hash: '../secret' }, { ...row, mime: '' },
      { ...row, filename: 42 }, { ...row, size: -1 }, { ...row, size: 0.5 },
      { ...row, source: 'private' }, { ...row, available: 'true' },
    ].map(input => ({ ...envelope, inputs: [input] })),
  ])('rejects malformed or cross-room data: %j', async body => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(body))));
    await expect(fetchThreadInputs('room/1')).rejects.toThrow('invalid room inputs response');
  });

  it('rejects malformed JSON', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{')));
    await expect(fetchThreadInputs('room/1')).rejects.toThrow();
  });
});
