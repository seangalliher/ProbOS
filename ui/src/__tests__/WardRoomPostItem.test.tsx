/**
 * AD-612: WardRoomPostItem — flat DM rendering + thread depth flattening.
 */
import { render, screen } from '@testing-library/react';
import { describe, it, expect, beforeEach, vi } from 'vitest';

import { renderWithStore } from '../test/renderHelpers';
import { WardRoomPostItem } from '../components/wardroom/WardRoomPostItem';
import type { WardRoomPost } from '../store/types';

// Mock fetch to prevent real API calls from ReplyInput
vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: true })));

function makePost(overrides: Partial<WardRoomPost> = {}): WardRoomPost {
  return {
    id: 'post-1',
    thread_id: 'thread-1',
    parent_id: null,
    author_id: 'agent-1',
    body: 'Test post body',
    created_at: Date.now() / 1000,
    edited_at: null,
    deleted: false,
    delete_reason: '',
    deleted_by: '',
    net_score: 0,
    author_callsign: 'Bones',
    ...overrides,
  };
}

describe('AD-612: Flat DM Rendering', () => {
  it('flat prop removes indentation', () => {
    const post = makePost();
    const { container } = renderWithStore(
      <WardRoomPostItem post={post} threadId="t1" flat />
    );
    const outerDiv = container.firstChild as HTMLElement;
    expect(outerDiv.style.marginLeft).toBe('0px');
    expect(outerDiv.style.paddingLeft).toBe('0px');
  });

  it('flat prop hides children', () => {
    const child = makePost({ id: 'child-1', body: 'Child post', author_callsign: 'Chapel' });
    const parent = makePost({ children: [child] });
    renderWithStore(
      <WardRoomPostItem post={parent} threadId="t1" flat />
    );
    expect(screen.queryByText('Child post')).not.toBeInTheDocument();
  });

  it('flat reply shows replying-to label', () => {
    const parentPost = makePost({ id: 'parent-1', author_callsign: 'Bones' });
    const replyPost = makePost({
      id: 'reply-1',
      parent_id: 'parent-1',
      author_callsign: 'Chapel',
      body: 'Reply body',
    });
    renderWithStore(
      <WardRoomPostItem post={replyPost} threadId="t1" flat allPosts={[parentPost, replyPost]} />
    );
    expect(screen.getByText(/replying to @Bones/)).toBeInTheDocument();
  });

  it('non-flat still indents', () => {
    const post = makePost();
    const { container } = renderWithStore(
      <WardRoomPostItem post={post} threadId="t1" depth={2} />
    );
    const outerDiv = container.firstChild as HTMLElement;
    expect(outerDiv.style.marginLeft).toBe('32px'); // 2 * 16
  });
});

describe('AD-612: Thread Depth Flattening', () => {
  it('max depth is 2', () => {
    // Build a chain: root -> child (depth 1) -> grandchild (depth 2) -> great-grandchild
    const greatGrandchild = makePost({ id: 'ggc', body: 'GGC body', author_callsign: 'Data' });
    const grandchild = makePost({ id: 'gc', body: 'GC body', author_callsign: 'Chapel', children: [greatGrandchild] });
    const child = makePost({ id: 'c', body: 'Child body', author_callsign: 'Atlas', children: [grandchild] });
    const root = makePost({ id: 'r', body: 'Root body', children: [child] });

    const { container } = renderWithStore(
      <WardRoomPostItem post={root} threadId="t1" depth={0} />
    );
    // All posts should render (recursion still happens, just capped at depth 2)
    expect(screen.getByText('Root body')).toBeInTheDocument();
    expect(screen.getByText('Child body')).toBeInTheDocument();
    expect(screen.getByText('GC body')).toBeInTheDocument();
    expect(screen.getByText('GGC body')).toBeInTheDocument();
  });

  it('depth >= 2 shows replying-to with parentCallsign', () => {
    const post = makePost({ body: 'Deep post' });
    renderWithStore(
      <WardRoomPostItem post={post} threadId="t1" depth={2} parentCallsign="Atlas" />
    );
    expect(screen.getByText(/replying to @Atlas/)).toBeInTheDocument();
  });

  it('depth 0 has no back-reference', () => {
    const post = makePost({ body: 'Root post' });
    renderWithStore(
      <WardRoomPostItem post={post} threadId="t1" depth={0} />
    );
    expect(screen.queryByText(/replying to/)).not.toBeInTheDocument();
  });
});
