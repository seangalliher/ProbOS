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
