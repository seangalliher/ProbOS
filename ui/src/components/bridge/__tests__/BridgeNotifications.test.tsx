// AD-1053: NotificationCard renders an "Accept" button only when the
// notification carries a producer-authored suggested_action.label, and clicking
// it POSTs to /api/notifications/{id}/accept (stopPropagation so the card's ack
// handler does not also fire). HXI no-emoji guard (#3). Real component; the
// global fetch is stubbed.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent } from '@testing-library/react';

import { NotificationCard } from '../BridgeNotifications';
import cardSource from '../BridgeNotifications.tsx?raw';
import type { NotificationView } from '../../../store/types';

const EMOJI_RE = /\p{Extended_Pictographic}/u;

function makeNotification(overrides: Partial<NotificationView> = {}): NotificationView {
  return {
    id: 'n1',
    agent_id: 'p',
    agent_type: 'producer',
    department: 'ops',
    notification_type: 'action_required',
    title: 't',
    detail: 'd',
    action_url: '',
    created_at: 0,
    acknowledged: false,
    ...overrides,
  };
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn(() => Promise.resolve({ ok: true } as Response));
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe('AD-1053 NotificationCard accept affordance', () => {
  it('renders an Accept button and POSTs to the accept endpoint on click', () => {
    const n = makeNotification({
      suggested_action: { label: 'Do it', intent: 'direct_message' },
    });
    render(<NotificationCard notification={n} />);

    const btn = screen.getByTestId('notification-accept');
    expect(btn).toHaveTextContent('Do it');

    fireEvent.click(btn);

    // stopPropagation -> only the accept endpoint is hit, not the card's /ack.
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith('/api/notifications/n1/accept', { method: 'POST' });
  });

  it('renders no Accept button when suggested_action is absent (byte-identical card)', () => {
    render(<NotificationCard notification={makeNotification()} />);

    expect(screen.queryByTestId('notification-accept')).toBeNull();
  });

  it('contains no emoji (HXI #3) in source or rendered DOM', () => {
    expect(cardSource).not.toMatch(EMOJI_RE);

    const n = makeNotification({
      suggested_action: { label: 'Do it', intent: 'direct_message' },
    });
    const { container } = render(<NotificationCard notification={n} />);

    expect(container.textContent ?? '').not.toMatch(EMOJI_RE);
  });
});
