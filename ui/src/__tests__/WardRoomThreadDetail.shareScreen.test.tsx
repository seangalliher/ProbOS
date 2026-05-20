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

  // BF-317 — discoverability polish (text label + size diff + separator).
  it('BF-317: renders persistent "Share screen" text label beside the icon', () => {
    render(<WardRoomThreadDetail />);
    const btn = screen.getByTestId('wardroom-dm-share-screen-button');
    // Label text must be reachable AND inside the share-screen button element.
    const label = screen.getByText('Share screen');
    expect(label).toBeTruthy();
    expect(btn.contains(label)).toBe(true);
  });

  it('BF-317: share-screen button is visually distinct from attach button', () => {
    render(<WardRoomThreadDetail />);
    const shareBtn = screen.getByTestId('wardroom-dm-share-screen-button');
    const attachBtn = screen.getByTestId('wardroom-dm-attach-button');
    const shareSvg = shareBtn.querySelector('svg');
    const attachSvg = attachBtn.querySelector('svg');
    expect(shareSvg).toBeTruthy();
    expect(attachSvg).toBeTruthy();
    // Size differentiation: share-screen glyph is 18 vs attach 14.
    expect(shareSvg!.getAttribute('width')).toBe('18');
    expect(attachSvg!.getAttribute('width')).toBe('14');
    // Filled vs stroke-only: share-screen has at least one fill attr that is NOT "none".
    const shareFills = Array.from(shareSvg!.querySelectorAll('[fill]'))
      .map(el => el.getAttribute('fill'));
    expect(shareFills.some(f => f !== null && f !== 'none')).toBe(true);
    // Attach paperclip is stroke-only — its svg root has fill="none".
    expect(attachSvg!.getAttribute('fill')).toBe('none');
  });

  it('BF-317: divider element separates attach button from share-screen button', () => {
    render(<WardRoomThreadDetail />);
    const attachBtn = screen.getByTestId('wardroom-dm-attach-button');
    const shareBtn = screen.getByTestId('wardroom-dm-share-screen-button');
    const sep = screen.getByTestId('wardroom-dm-composer-separator');
    expect(sep).toBeTruthy();
    expect(sep.getAttribute('role')).toBe('separator');
    // Document-order: attach precedes separator, separator precedes share.
    const order = attachBtn.compareDocumentPosition(sep) & Node.DOCUMENT_POSITION_FOLLOWING;
    const order2 = sep.compareDocumentPosition(shareBtn) & Node.DOCUMENT_POSITION_FOLLOWING;
    expect(order).toBeGreaterThan(0);
    expect(order2).toBeGreaterThan(0);
  });
});
