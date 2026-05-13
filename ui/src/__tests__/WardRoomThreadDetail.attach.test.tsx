/**
 * AD-730-1 (Wave 154): WardRoomThreadDetail attach button.
 *
 * Three Vitest tests:
 * 1. Paperclip hidden in non-DM (channels) view.
 * 2. Paperclip visible in DM view with resolved target_agent_id.
 * 3. Picker-uploaded attachment flows through to /api/agent/{id}/chat body.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { WardRoomThreadDetail } from '../components/wardroom/WardRoomThreadDetail';
import { useStore } from '../store/useStore';

const FAKE_THREAD = {
  id: 't1', title: 'Test DM', body: '', author_callsign: 'Captain',
  created_at: Date.now() / 1000, net_score: 0,
};

function setDmView() {
  useStore.setState({
    wardRoomView: 'dm-detail',
    wardRoomActiveChannel: 'ch-1',
    wardRoomActiveThread: 't1',
    wardRoomThreadDetail: { thread: FAKE_THREAD as any, posts: [] },
    wardRoomDmChannels: [
      { channel: { id: 'ch-1', name: 'dm-captain-agent-a', description: '', created_at: 0 },
        latest_thread: null, thread_count: 1, target_agent_id: 'agent-a-001-full' },
    ],
    wardRoomDmPending: null,
  });
}

beforeEach(() => {
  vi.restoreAllMocks();
  setDmView();
});

describe('AD-730-1 WardRoomThreadDetail attach button', () => {
  it('paperclip is hidden in non-DM (channels) view', () => {
    useStore.setState({ wardRoomView: 'channels' });
    render(<WardRoomThreadDetail />);
    expect(screen.queryByTestId('wardroom-dm-attach-button')).toBeNull();
  });

  it('paperclip is visible in DM view with resolved target_agent_id', () => {
    render(<WardRoomThreadDetail />);
    const btn = screen.getByTestId('wardroom-dm-attach-button');
    expect(btn).toBeTruthy();
    expect(btn.getAttribute('aria-label')).toBe('attach file');
  });

  it('uploaded attachment_ids are included in the /api/agent/{id}/chat body', async () => {
    const fetchMock = vi.spyOn(global, 'fetch').mockImplementation(async (url: any) => {
      const u = String(url);
      if (u.includes('/api/chat/attachments/multipart')) {
        return new Response(JSON.stringify({ attachment_id: 'abc123', mime: 'image/png' }), { status: 200 });
      }
      if (u.includes('/api/agent/')) {
        return new Response(JSON.stringify({ response: 'ok' }), { status: 200 });
      }
      return new Response('{}', { status: 200 });
    }) as any;

    render(<WardRoomThreadDetail />);

    // Simulate a file picker change: drop a fake PNG into the hidden input.
    const file = new File([new Uint8Array([0x89, 0x50, 0x4e, 0x47])], 'cat.png', { type: 'image/png' });
    const inputs = document.querySelectorAll('input[type="file"]');
    expect(inputs.length).toBeGreaterThan(0);
    const fileInput = inputs[0] as HTMLInputElement;
    Object.defineProperty(fileInput, 'files', { value: [file], configurable: true });
    fireEvent.change(fileInput);

    // Wait for the chip to render (signals upload success path).
    await waitFor(() => {
      expect(screen.getByTestId('wardroom-dm-attachment-chips')).toBeTruthy();
    });

    // Now send.
    fireEvent.change(screen.getByPlaceholderText('Reply...'), { target: { value: 'look at this' } });
    fireEvent.click(screen.getByText('Send'));

    await waitFor(() => {
      const agentCall = fetchMock.mock.calls.find(
        (c: unknown[]) => String(c[0]).includes('/api/agent/agent-a-001-full/chat'),
      );
      expect(agentCall).toBeTruthy();
      const body = JSON.parse(String((agentCall![1] as RequestInit).body));
      expect(body.attachment_ids).toEqual(['abc123']);
    });
  });
});

// AD-730-1-1: paste and drag/drop image upload in the WardRoomThreadDetail
// reply composer. Augments the AD-730-1 file-picker tests above.
describe('AD-730-1-1 WardRoomThreadDetail paste/drop image', () => {
  function mockMultipartFetch() {
    return vi.spyOn(global, 'fetch').mockImplementation(async (url: any) => {
      if (String(url).includes('/api/chat/attachments/multipart')) {
        return new Response(
          JSON.stringify({ attachment_id: 'att-cat-1', filename: 'cat.png', size: 4, mime: 'image/png' }),
          { status: 200 },
        );
      }
      return new Response('{}', { status: 200 });
    }) as any;
  }

  it('paste image triggers upload and adds chip', async () => {
    const fetchMock = mockMultipartFetch();
    render(<WardRoomThreadDetail />);
    const textarea = screen.getByPlaceholderText('Reply...') as HTMLTextAreaElement;

    const file = new File([new Uint8Array([1, 2, 3, 4])], 'cat.png', { type: 'image/png' });
    const clipboardData = { items: [{ type: 'image/png', getAsFile: () => file }] };
    fireEvent.paste(textarea, { clipboardData });

    await waitFor(() => {
      const calls = fetchMock.mock.calls.map((c: unknown[]) => String(c[0]));
      expect(calls).toContain('/api/chat/attachments/multipart');
    });
    const chips = await screen.findByTestId('wardroom-dm-attachment-chips');
    // Pasted images get a synthesized name `pasted-<ts>.<ext>` because the
    // clipboard File blob has no filename of its own.
    expect(chips.textContent).toMatch(/pasted-\d+\.png/);
  });

  it('drop image triggers upload and adds chip', async () => {
    const fetchMock = mockMultipartFetch();
    render(<WardRoomThreadDetail />);
    const textarea = screen.getByPlaceholderText('Reply...') as HTMLTextAreaElement;
    // Reply container is the direct parent of the textarea (the wrapper that
    // received onDrop/onDragOver).
    const replyContainer = textarea.parentElement as HTMLElement;
    expect(replyContainer).toBeTruthy();

    const file = new File([new Uint8Array([1, 2, 3, 4])], 'cat.png', { type: 'image/png' });
    fireEvent.dragOver(replyContainer, { dataTransfer: { files: [file] } });
    fireEvent.drop(replyContainer, { dataTransfer: { files: [file] } });

    await waitFor(() => {
      const calls = fetchMock.mock.calls.map((c: unknown[]) => String(c[0]));
      expect(calls).toContain('/api/chat/attachments/multipart');
    });
    const chips = await screen.findByTestId('wardroom-dm-attachment-chips');
    expect(chips.textContent).toContain('cat.png');
  });

  it('paste plain text does not trigger upload', () => {
    const fetchMock = mockMultipartFetch();
    render(<WardRoomThreadDetail />);
    const textarea = screen.getByPlaceholderText('Reply...') as HTMLTextAreaElement;

    const clipboardData = { items: [{ type: 'text/plain', getAsFile: () => null }] };
    fireEvent.paste(textarea, { clipboardData });

    const calls = fetchMock.mock.calls.map((c: unknown[]) => String(c[0]));
    expect(calls).not.toContain('/api/chat/attachments/multipart');
  });
});
