// AD-720: image-paste handler, preview thumbnails, paperclip placeholder, no emoji.

import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, act, waitFor } from '@testing-library/react';
import { IntentSurface } from '../components/IntentSurface';
import { useStore } from '../store/useStore';

const EMOJI_RE = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{1F600}-\u{1F64F}]/u;

beforeEach(() => {
  useStore.setState({
    chatHistory: [],
    activeDag: [],
    pendingRequests: 0,
    agents: new Map(),
  });
  // crypto.subtle.digest stub (jsdom has no SubtleCrypto by default).
  Object.defineProperty(global, 'crypto', {
    value: {
      subtle: {
        digest: vi.fn(async (_alg: string, _buf: ArrayBuffer) => {
          // Return a 32-byte buffer of constant 0xab.
          const arr = new Uint8Array(32).fill(0xab);
          return arr.buffer;
        }),
      },
    },
    configurable: true,
  });
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({
      attachment_id: 'ab'.repeat(32),
      url: '/api/chat/attachments/' + 'ab'.repeat(32),
      mime: 'image/png',
      sha256: 'ab'.repeat(32),
      size_bytes: 8,
    }),
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function openShell() {
  render(<IntentSurface />);
  const pillText = screen.queryByText(/Ask ProbOS/);
  if (pillText) {
    const clickable = pillText.closest('div');
    if (clickable) fireEvent.click(clickable);
  }
}

function getInput(): HTMLInputElement {
  const input = document.querySelector('input[placeholder="Ask ProbOS..."]') as HTMLInputElement | null;
  if (!input) throw new Error('IntentSurface input did not mount');
  return input;
}

function makePastEvent(blobType: string, bytes: number) {
  const blob = new Blob([new Uint8Array(bytes)], { type: blobType });
  const file = new File([blob], 'paste.png', { type: blobType });
  return {
    clipboardData: {
      items: [
        {
          type: blobType,
          getAsFile: () => file,
        },
      ],
    },
    preventDefault: vi.fn(),
  };
}

describe('IntentSurface AD-720 — image paste', () => {
  it('paperclip placeholder is rendered as inline SVG (no emoji)', () => {
    openShell();
    const paper = screen.queryByTestId('attachment-paperclip');
    expect(paper).toBeTruthy();
    expect(paper!.textContent || '').not.toMatch(EMOJI_RE);
    // Hovering opens tooltip.
    fireEvent.mouseEnter(paper!);
    expect(screen.queryByTestId('attachment-paperclip-tooltip')).toBeTruthy();
  });

  it('pasting an image POSTs to /api/chat/attachments and renders preview', async () => {
    openShell();
    const input = getInput();
    await act(async () => {
      fireEvent.paste(input, makePastEvent('image/png', 8));
    });
    await waitFor(() => {
      expect((global.fetch as any)).toHaveBeenCalledWith(
        '/api/chat/attachments',
        expect.objectContaining({ method: 'POST' }),
      );
    });
    await waitFor(() => {
      expect(screen.queryByTestId('attachment-preview')).toBeTruthy();
    });
  });

  it('clicking the inline-SVG x removes the preview', async () => {
    openShell();
    const input = getInput();
    await act(async () => {
      fireEvent.paste(input, makePastEvent('image/png', 8));
    });
    await waitFor(() => expect(screen.queryByTestId('attachment-preview')).toBeTruthy());
    const removeBtn = screen.getByTestId('attachment-remove');
    expect((removeBtn.textContent || '')).not.toMatch(EMOJI_RE);
    fireEvent.click(removeBtn);
    await waitFor(() => {
      expect(screen.queryByTestId('attachment-preview')).toBeNull();
    });
  });

  it('non-image clipboard items are ignored (no fetch)', async () => {
    openShell();
    const input = getInput();
    (global.fetch as any).mockClear();
    fireEvent.paste(input, {
      clipboardData: {
        items: [{ type: 'text/plain', getAsFile: () => null }],
      },
      preventDefault: vi.fn(),
    });
    const calls = (global.fetch as any).mock.calls.filter((c: any[]) => String(c[0]).includes('/api/chat/attachments'));
    expect(calls.length).toBe(0);
  });

  it('oversize blob shows structured error and does not POST', async () => {
    openShell();
    const input = getInput();
    const big = 11 * 1024 * 1024;
    (global.fetch as any).mockClear();
    await act(async () => {
      fireEvent.paste(input, makePastEvent('image/png', big));
    });
    const calls = (global.fetch as any).mock.calls.filter((c: any[]) => String(c[0]).includes('/api/chat/attachments'));
    expect(calls.length).toBe(0);
    // A system message should be present in the chat history.
    const history = useStore.getState().chatHistory;
    const last = history[history.length - 1];
    expect(last?.role).toBe('system');
    expect(last?.text).toContain('Attachment too large');
  });

  it('preview strip emits no emoji codepoints', async () => {
    openShell();
    const input = getInput();
    await act(async () => {
      fireEvent.paste(input, makePastEvent('image/png', 8));
    });
    await waitFor(() => expect(screen.queryByTestId('attachment-preview')).toBeTruthy());
    const strip = screen.getByTestId('attachment-preview-strip');
    expect((strip.textContent || '')).not.toMatch(EMOJI_RE);
  });
});
