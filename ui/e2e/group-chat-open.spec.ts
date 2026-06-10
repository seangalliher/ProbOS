// AD-941 Issue 2 — the headline regression: clicking a group row in CHATS must
// open the room as a GROUP (its real, thread-keyed transcript), NOT an empty
// host 1:1. This is the integration the mocked-store Vitest suite could not
// cover: real store + real ChatsPanel/AgentProfilePanel/ProfileChatTab +
// real AD-937 open-routing + the AD-938 load-on-open transcript fetch.
import { test, expect } from '@playwright/test';
import { EZRI, YEO, mkThread, mkMessage, mockChatApi, gotoApp, seedAgents, openChats } from './_helpers';

test.describe('AD-941 Issue 2 — group opens with its real transcript', () => {
  test('group row opens the room (title + both avatars + Start meeting + transcript)', async ({ page }) => {
    const group = mkThread('g1', 'Ezri, Yeo', ['ezri', 'yeo']);
    const oneToOne = mkThread('d1', 'Kira', ['kira']);
    const msgEzri = mkMessage('m1', 'g1', 'ezri', 'agent', 'Reactor holding at nominal, Captain.', 1000);
    const msgYeo = mkMessage('m2', 'g1', 'yeo', 'agent', 'Logged and filed, sir.', 1001);

    await mockChatApi(page, { threads: [group, oneToOne], messagesByThread: { g1: [msgEzri, msgYeo] } });
    await gotoApp(page);
    await seedAgents(page, [EZRI, YEO]);
    await openChats(page);

    // The panel lists the group row (from the mocked GET /api/threads); open it.
    await page.getByTestId('chat-row-g1').click();

    // Group header: the room title + BOTH participant avatars + Start call.
    await expect(page.getByTestId('group-chat-title')).toHaveText('Ezri, Yeo');
    await expect(page.getByTestId('group-chat-header').getByLabel('Agent Ezri')).toBeVisible();
    await expect(page.getByTestId('group-chat-header').getByLabel('Agent Yeo')).toBeVisible();
    // AD-954: the meeting toggle is framed as "Start call" (Teams mental model).
    await expect(page.getByTestId('meeting-toggle')).toHaveAttribute('aria-label', 'Start call');

    // The real thread transcript renders (NOT an empty host 1:1): both mocked
    // messages appear, with two AD-936 per-author metadata rows.
    await expect(page.getByText('Reactor holding at nominal, Captain.')).toBeVisible();
    await expect(page.getByText('Logged and filed, sir.')).toBeVisible();
    await expect(page.getByTestId('chat-msg-time')).toHaveCount(2);
  });
});
