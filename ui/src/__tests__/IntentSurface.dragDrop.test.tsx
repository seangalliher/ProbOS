// AD-720a (Wave 139): drag-drop overlay + file picker + multipart upload + non-image preview badges.

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
  // No crypto.subtle needed — multipart path computes sha256 server-side.
  global.fetch = vi.fn().mockImplementation(async (url: string, init?: RequestInit) => {
    if (typeof url === 'string' && url.endsWith('/multipart')) {
      const fd = init?.body as FormData;
      const file = fd?.get('file') as File | null;
      const filename = file?.name ?? 'unknown';
      const mime = file?.type ?? 'application/octet-stream';
      return {
        ok: true,
        json: async () => ({
          attachment_id: 'cd'.repeat(32),
          url: '/api/chat/attachments/' + 'cd'.repeat(32),
          mime,
          sha256: 'cd'.repeat(32),
          size_bytes: file?.size ?? 0,
          // server response intentionally does NOT echo filename — UI keeps it
          _debug_filename: filename,
        }),
      };
    }
    return { ok: false, json: async () => ({ error: 'unexpected' }) };
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

function getComposerForm(): HTMLFormElement {
  const input = document.querySelector('input[placeholder="Ask ProbOS..."]') as HTMLInputElement | null;
  if (!input) throw new Error('IntentSurface input did not mount');
  const form = input.closest('form');
  if (!form) throw new Error('IntentSurface form did not mount');
  return form as HTMLFormElement;
}

describe('IntentSurface AD-720a — drag-drop + file picker', () => {
  it('drag-drop overlay shows on dragenter and disappears on dragleave', async () => {
    openShell();
    const form = getComposerForm();
    expect(screen.queryByTestId('drag-drop-overlay')).toBeNull();

    // dragEnter with type "Files" opens the overlay.
    await act(async () => {
      fireEvent.dragEnter(form, {
        dataTransfer: { types: ['Files'], files: [] },
      });
    });
    expect(screen.queryByTestId('drag-drop-overlay')).toBeTruthy();

    // dragLeave on the form itself closes it.
    await act(async () => {
      fireEvent.dragLeave(form, { dataTransfer: { types: ['Files'] } });
    });
    expect(screen.queryByTestId('drag-drop-overlay')).toBeNull();
  });

  it('file picker accept attribute lists all 9 allowed MIMEs', () => {
    openShell();
    const fileInput = screen.getByTestId('attachment-file-input') as HTMLInputElement;
    const accept = fileInput.getAttribute('accept') ?? '';
    for (const mime of [
      'image/png', 'image/jpeg', 'image/webp', 'image/gif',
      'application/pdf', 'text/plain', 'text/markdown',
      'application/json', 'text/csv',
    ]) {
      expect(accept).toContain(mime);
    }
  });

  it('drop of a .txt file renders a filename badge (not <img>) in the preview strip', async () => {
    openShell();
    const form = getComposerForm();
    const file = new File([new Uint8Array([0x68, 0x69])], 'notes.txt', { type: 'text/plain' });
    await act(async () => {
      fireEvent.drop(form, {
        dataTransfer: { types: ['Files'], files: [file] },
      });
    });
    await waitFor(() => {
      const previews = screen.queryAllByTestId('attachment-preview');
      expect(previews.length).toBeGreaterThanOrEqual(1);
    });
    const preview = screen.getAllByTestId('attachment-preview')[0]!;
    // Filename badge — NOT an <img>.
    expect(preview.querySelector('img')).toBeNull();
    expect(preview.textContent || '').toContain('notes.txt');
  });

  it('error toast (system message) renders on oversize / mime-reject from server', async () => {
    openShell();
    const form = getComposerForm();
    // Make fetch reject with 413.
    (global.fetch as any) = vi.fn().mockResolvedValue({
      ok: false,
      json: async () => ({ error: 'too_large', size: 99, max: 64 }),
    });
    const file = new File([new Uint8Array([0x68, 0x69])], 'big.png', { type: 'image/png' });
    await act(async () => {
      fireEvent.drop(form, {
        dataTransfer: { types: ['Files'], files: [file] },
      });
    });
    await waitFor(() => {
      const history = useStore.getState().chatHistory;
      expect(history.some((m) => m.role === 'system' && /upload failed.*too_large/i.test(m.text))).toBe(true);
    });
  });

  it('drag-drop overlay and picker affordances contain no emoji codepoints', async () => {
    openShell();
    const form = getComposerForm();
    await act(async () => {
      fireEvent.dragEnter(form, { dataTransfer: { types: ['Files'], files: [] } });
    });
    const overlay = screen.getByTestId('drag-drop-overlay');
    expect(overlay.textContent || '').not.toMatch(EMOJI_RE);
    const paperclip = screen.getByTestId('attachment-paperclip');
    expect(paperclip.textContent || '').not.toMatch(EMOJI_RE);
  });
});
