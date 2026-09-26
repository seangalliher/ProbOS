// AD-1214 (#1171): a delegated decision's notification can offer to pre-clear
// its exact class. An offer card shows its detail IN FULL -- the Captain
// consents to text they can read -- with a Pre-clear control that posts only the
// opaque offer id to the operator-scoped route, and an Undo on the same card.
// Every other card is unchanged: the 120-character cut, and no control. Real
// component; the global fetch is stubbed.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';

import { NotificationCard } from '../BridgeNotifications';
import { useStore } from '../../../store/useStore';
import type { NotificationView } from '../../../store/types';

const initialStoreState = useStore.getState();
const OFFER = 'a'.repeat(32);
const RECORD = '0f8f5a3e-8a41-4a8e-9b0e-3d7c2f1e9a10';
const EXPIRES = 2_000_000_000;
const ROUTE = '/api/decision-pre-clearances';
const SENTENCE = 'Pre-clear offer (AD-1214): for 24 hours after you accept, you will not be notified '
  + 'when the chief_engineer post, acting as department chief, approves a request from the engineering '
  + "department to grant tool 'calc_tool' (class non_destructive). Each such decision is still audited, "
  + 'and nothing else is pre-cleared.';
// AD-1213's detail for the P-A fixture: 216 characters, cut before the target at 120.
const AD1213_DETAIL = 'Department chief engineering_officer_engineering_officer_0_872b75e7 approved '
  + "builder_builder_0_0e6917c3's grant request for 'calc_tool'. Class: non_destructive. "
  + 'Reason: Routine read access. Not pre-cleared (AD-1213).';

function makeNotification(overrides: Partial<NotificationView> = {}): NotificationView {
  return {
    id: 'n1',
    agent_id: 'engineering_officer_engineering_officer_0_872b75e7',
    agent_type: 'engineering_officer',
    department: 'engineering',
    notification_type: 'info',
    title: 'Delegated decision: approved grant request 0e6917c3',
    detail: `${AD1213_DETAIL} ${SENTENCE}`,
    action_url: `approval-pre-clear:${OFFER}`,
    created_at: 0,
    acknowledged: false,
    ...overrides,
  };
}

function created(): Response {
  return new Response(JSON.stringify({
    pre_clearance: { id: RECORD, expires_at: EXPIRES }, requested_hours: 24, granted_hours: 24, clamped: false,
  }), { status: 201 });
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn(() => Promise.resolve(created()));
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  cleanup();
  useStore.setState(initialStoreState, true);
  window.history.replaceState(null, '', '/');
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe('AD-1214 NotificationCard pre-clear offer', () => {
  it("renders an offer card's full detail, scope sentence included, with a Pre-clear control", () => {
    const notification = makeNotification();
    expect(notification.detail.length).toBeGreaterThan(200); // premise: the old cut would hide the sentence
    const { container } = render(<NotificationCard notification={notification} />);

    expect(container.textContent).toContain(notification.detail);
    expect(container.textContent).toContain(SENTENCE);
    expect(container.textContent).not.toContain('\u2026');
    const control = screen.getByTestId('notification-pre-clear');
    expect(control).toHaveTextContent('Pre-clear');
    expect(control).toBeEnabled();
    const open = screen.getByRole('button', { name: /^Open room context/ });
    expect(open.contains(control)).toBe(false); // a sibling, never nested in the open button
    expect(screen.queryByTestId('notification-pre-clear-undo')).toBeNull();
    expect(screen.queryByTestId('notification-pre-clear-status')).toBeNull();
  });

  it('keeps the 120-character cut and shows no control for a card without an offer', () => {
    expect(AD1213_DETAIL.length).toBe(216);
    const { container } = render(
      <NotificationCard notification={makeNotification({ detail: AD1213_DETAIL, action_url: '' })} />,
    );

    expect(container.textContent).toContain(AD1213_DETAIL.slice(0, 120) + '\u2026');
    expect(container.textContent).not.toContain(AD1213_DETAIL);
    expect(screen.queryByTestId('notification-pre-clear')).toBeNull();
    expect(screen.queryByTestId('notification-pre-clear-status')).toBeNull();
  });

  it.each([
    ['uppercase hex', `approval-pre-clear:${'A'.repeat(32)}`],
    ['31 hex', `approval-pre-clear:${'a'.repeat(31)}`],
    ['33 hex', `approval-pre-clear:${'a'.repeat(33)}`],
    ['trailing text', `approval-pre-clear:${OFFER} again`],
    ['a thread marker', 'thread:x'],
    ['an https URL', `https://example.com/approval-pre-clear:${OFFER}`],
    ['empty', ''],
  ])('shows no control for a near-miss action_url (%s)', (_label, actionUrl) => {
    const notification = makeNotification({ action_url: actionUrl });
    const { container } = render(<NotificationCard notification={notification} />);

    expect(screen.queryByTestId('notification-pre-clear')).toBeNull();
    expect(container.textContent).toContain(notification.detail.slice(0, 120) + '\u2026');
    expect(container.textContent).not.toContain(SENTENCE);
  });

  it('posts only the offer id to the Captain route, with the token, and reports the expiry', async () => {
    window.history.replaceState(null, '', '/?token=secret');
    render(<NotificationCard notification={makeNotification()} />);

    fireEvent.click(screen.getByTestId('notification-pre-clear'));

    await waitFor(() => expect(screen.getByTestId('notification-pre-clear-status')).toHaveTextContent(
      `Pre-cleared until ${new Date(EXPIRES * 1000).toLocaleString()}.`,
    ));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(ROUTE);
    expect(init).toMatchObject({ method: 'POST', mode: 'same-origin', redirect: 'error', cache: 'no-store' });
    expect(init.body).toBe(JSON.stringify({ offer_id: OFFER }));
    expect(init.headers).toEqual({ 'Content-Type': 'application/json', Authorization: 'Bearer secret' });
    expect(screen.queryByTestId('notification-pre-clear')).toBeNull();
    expect(screen.getByTestId('notification-pre-clear-undo')).toHaveTextContent('Undo pre-clearance');
    expect(screen.getByTestId('notification-pre-clear-status')).toHaveAttribute('role', 'status');
  });

  it.each([
    ['refusal', () => Promise.resolve(new Response('{}', { status: 401 })), 'Pre-clear refused: authentication required.'],
    ['lapsed offer', () => Promise.resolve(new Response('{}', { status: 404 })),
      'This offer has lapsed; the next decision of this class offers it again.'],
    ['server failure', () => Promise.resolve(new Response('{}', { status: 503 })), 'Pre-clear failed (503). Retry to try again.'],
    ['malformed success', () => Promise.resolve(new Response('{"pre_clearance":{"id":7}}', { status: 201 })),
      'Pre-clear failed (201). Retry to try again.'],
    ['network failure', () => Promise.reject(new Error('offline')), 'Pre-clear failed. Retry to try again.'],
  ])('reports a %s without touching the context message', async (_label, respond, text) => {
    fetchMock.mockImplementation(respond);
    render(<NotificationCard notification={makeNotification()} />);

    fireEvent.click(screen.getByTestId('notification-pre-clear'));

    await waitFor(() => expect(screen.getByTestId('notification-pre-clear-status')).toHaveTextContent(text));
    expect(text).not.toMatch(/unavailable|cancelled/);
    expect(screen.queryByRole('button', { name: 'Retry opening context' })).toBeNull();
    expect(screen.queryByText(/Context unavailable|Opening room context/)).toBeNull();
    expect(screen.getByTestId('notification-pre-clear')).toBeEnabled(); // the Captain can retry
    expect(screen.queryByTestId('notification-pre-clear-undo')).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('undoes a pre-clearance from the same card', async () => {
    window.history.replaceState(null, '', '/?token=secret');
    fetchMock
      .mockResolvedValueOnce(created())
      .mockResolvedValueOnce(new Response('{}', { status: 500 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ revoked: 1 }), { status: 200 }));
    render(<NotificationCard notification={makeNotification()} />);
    fireEvent.click(screen.getByTestId('notification-pre-clear'));

    fireEvent.click(await screen.findByTestId('notification-pre-clear-undo'));
    await waitFor(() => expect(screen.getByTestId('notification-pre-clear-status')).toHaveTextContent(
      'Pre-clear failed (500). Retry to try again.',
    ));
    fireEvent.click(screen.getByTestId('notification-pre-clear-undo')); // a failed undo can be retried

    await waitFor(() => expect(screen.getByTestId('notification-pre-clear-status')).toHaveTextContent(
      'Pre-clearance undone; this class notifies again.',
    ));
    expect(fetchMock).toHaveBeenCalledTimes(3);
    for (const [url, init] of fetchMock.mock.calls.slice(1)) {
      expect(url).toBe(`${ROUTE}/${RECORD}`);
      expect(init).toMatchObject({ method: 'DELETE', mode: 'same-origin', redirect: 'error', cache: 'no-store' });
      expect(init.headers).toEqual({ Authorization: 'Bearer secret' });
      expect(init.body).toBeUndefined();
    }
    expect(screen.queryByTestId('notification-pre-clear-undo')).toBeNull();
    expect(screen.queryByTestId('notification-pre-clear')).toBeNull();
  });

  it('pre-clearing does not open the room context', async () => {
    const bubbled = vi.fn();
    render(<div onClick={bubbled}><NotificationCard notification={makeNotification()} /></div>);

    fireEvent.click(screen.getByTestId('notification-pre-clear'));
    const undo = await screen.findByTestId('notification-pre-clear-undo');
    fetchMock.mockImplementation(() => Promise.resolve(new Response('{"revoked":1}', { status: 200 })));
    fireEvent.click(undo);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const paths = fetchMock.mock.calls.map(([path]) => String(path));
    expect(paths).toEqual([ROUTE, `${ROUTE}/${RECORD}`]);
    expect(paths.some(path => /\/context|\/accept|\/ack/.test(path))).toBe(false);
    expect(bubbled).not.toHaveBeenCalled();
    expect(useStore.getState().notificationNavigation).toBeNull();
    expect(screen.queryByText('Opening room context...')).toBeNull();
  });
});
