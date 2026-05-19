/**
 * AD-744: WardRoomThreadDetail share-screen button.
 *
 * Three Vitest tests:
 * 1. Share button hidden in non-DM (channels) view.
 * 2. Share button visible in DM view alongside paperclip.
 * 3. Successful share appends attachment_id to pendingAttachments (chip strip).
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { WardRoomThreadDetail } from '../components/wardroom/WardRoomThreadDetail';
import { useStore } from '../store/useStore';

const FAKE_THREAD = {
  id: 't1', title: 'Share Test DM', body: '', author_callsign: 'Captain',
  created_at: Date.now() / 1000, net_score: 0,
};

function setDmView() {
  useStore.setState({
    wardRoomView: 'dm-detail',
    wardRoomActiveChannel: 'ch-1',
    wardRoomActiveThread: 't1',
    wardRoomThreadDetail: { thread: FAKE_THREAD as any, posts: [] },
    wardRoomDmChannels: [
      { channel: { id: 'ch-1', name: 'dm-captain-counselor', description: '', created_at: 0 },
        latest_thread: null, thread_count: 1, target_agent_id: 'counselor-001' },
    ],
    wardRoomDmPending: null,
  });
}

beforeEach(() => {
  vi.restoreAllMocks();
  setDmView();
});

describe('AD-744 WardRoomThreadDetail share-screen button', () => {
  it('share button is hidden in non-DM (channels) view', () => {
    useStore.setState({ wardRoomView: 'channels' });
    render(<WardRoomThreadDetail />);
    expect(screen.queryByTestId('wardroom-dm-share-screen-button')).toBeNull();
  });

  it('share button is visible in DM view with resolved target_agent_id', () => {
    render(<WardRoomThreadDetail />);
    const btn = screen.getByTestId('wardroom-dm-share-screen-button');
    expect(btn).toBeTruthy();
    expect(btn.getAttribute('aria-label')).toBe('share screen to agent');
  });

  it('successful share appends attachment_id to pendingAttachments', async () => {
    // Mock captureScreenShareFrame indirectly via getDisplayMedia + fetch.
    const fakeTrack = { stop: vi.fn(), kind: 'video', readyState: 'live' };
    const fakeStream = { getTracks: () => [fakeTrack] } as unknown as MediaStream;
    Object.defineProperty(global.navigator, 'mediaDevices', {
      value: { getDisplayMedia: vi.fn(async () => fakeStream) },
      configurable: true,
      writable: true,
    });
    // Canvas + video shims (same as useScreenShare.test.ts).
    const cProto = HTMLCanvasElement.prototype as unknown as {
      getContext: (k: string) => unknown;
      toBlob: (cb: (b: Blob | null) => void) => void;
    };
    cProto.getContext = () => ({ drawImage: () => undefined });
    cProto.toBlob = (cb) => cb(new Blob(['x'], { type: 'image/jpeg' }));
    Object.defineProperty(HTMLVideoElement.prototype, 'videoWidth', {
      configurable: true, get() { return 320; },
    });
    Object.defineProperty(HTMLVideoElement.prototype, 'videoHeight', {
      configurable: true, get() { return 200; },
    });
    HTMLVideoElement.prototype.play = vi.fn(async () => undefined);

    vi.spyOn(global, 'fetch').mockResolvedValue({
      status: 200, ok: true,
      json: async () => ({ ok: true, attachment_ref: 'sha-share-1' }),
    } as unknown as Response);

    render(<WardRoomThreadDetail />);
    fireEvent.click(screen.getByTestId('wardroom-dm-share-screen-button'));

    await waitFor(() => {
      expect(screen.getByTestId('wardroom-dm-attachment-chips')).toBeTruthy();
    });
  });
});
