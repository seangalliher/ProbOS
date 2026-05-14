// AD-720e (Wave 159): audio attachment renders as <audio controls>; non-image,
// non-audio falls back to file icon; image still renders as <img>.

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, act, waitFor } from '@testing-library/react';
import { IntentSurface } from '../components/IntentSurface';
import { useStore } from '../store/useStore';

function uploadResponse(mime: string, sha: string) {
  return {
    ok: true,
    json: async () => ({
      attachment_id: sha,
      url: '/api/chat/attachments/' + sha,
      mime,
      sha256: sha,
      size_bytes: 8,
    }),
  };
}

beforeEach(() => {
  useStore.setState({
    chatHistory: [],
    activeDag: [],
    pendingRequests: 0,
    agents: new Map(),
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

function makeDropEvent(file: File) {
  return {
    preventDefault: vi.fn(),
    dataTransfer: {
      files: [file],
      types: ['Files'],
    },
  };
}

async function dropFile(blob: Blob, name: string, mime: string) {
  const form = document.querySelector('form');
  if (!form) throw new Error('composer form not mounted');
  const file = new File([blob], name, { type: mime });
  await act(async () => {
    fireEvent.drop(form, makeDropEvent(file));
  });
}

describe('IntentSurface AD-720e — audio attachment render', () => {
  it('audio/mpeg attachment renders as <audio controls>', async () => {
    global.fetch = vi.fn().mockResolvedValue(uploadResponse('audio/mpeg', 'aa'.repeat(32))) as unknown as typeof fetch;
    openShell();
    const blob = new Blob([new Uint8Array([0x49, 0x44, 0x33, 0x03])], { type: 'audio/mpeg' });
    await dropFile(blob, 'clip.mp3', 'audio/mpeg');
    await waitFor(() => {
      expect(screen.queryByTestId('attachment-preview')).toBeTruthy();
    });
    const audio = document.querySelector('audio[controls]');
    expect(audio).toBeTruthy();
    expect((audio as HTMLAudioElement).src).toContain('/api/chat/attachments/' + 'aa'.repeat(32));
  });

  it('image/png attachment still renders as <img> (regression)', async () => {
    global.fetch = vi.fn().mockResolvedValue(uploadResponse('image/png', 'bb'.repeat(32))) as unknown as typeof fetch;
    openShell();
    const blob = new Blob([new Uint8Array([0x89, 0x50])], { type: 'image/png' });
    await dropFile(blob, 'pic.png', 'image/png');
    await waitFor(() => {
      expect(screen.queryByTestId('attachment-preview')).toBeTruthy();
    });
    expect(document.querySelector('img')).toBeTruthy();
    expect(document.querySelector('audio')).toBeNull();
  });

  it('application/pdf attachment renders the file-icon fallback', async () => {
    global.fetch = vi.fn().mockResolvedValue(uploadResponse('application/pdf', 'cc'.repeat(32))) as unknown as typeof fetch;
    openShell();
    const blob = new Blob([new Uint8Array([0x25, 0x50, 0x44, 0x46])], { type: 'application/pdf' });
    await dropFile(blob, 'doc.pdf', 'application/pdf');
    await waitFor(() => {
      expect(screen.queryByTestId('attachment-preview')).toBeTruthy();
    });
    expect(document.querySelector('img')).toBeNull();
    expect(document.querySelector('audio')).toBeNull();
    // File-icon branch renders an inline svg next to the filename.
    const preview = screen.getByTestId('attachment-preview');
    expect(preview.querySelector('svg')).toBeTruthy();
  });
});
