// AD-941 Issue 4 — Start meeting must render the Captain's gallery slot plus a
// live avatar slot for every crew participant. With no camera/screen stream the
// Captain slot falls back to the amber person glyph (captain-icon).
import { test, expect } from '@playwright/test';
import { EZRI, YEO, mkThread, mockChatApi, gotoApp, seedAgents, openGroupChat } from './_helpers';

test.describe('AD-941 Issue 4 — Start meeting renders captain + crew avatar slots', () => {
  test('captain-slot + avatar-slot per crew + captain-icon fallback (no camera)', async ({ page }) => {
    const group = mkThread('g1', 'Ezri, Yeo', ['ezri', 'yeo']);
    await mockChatApi(page, { threads: [group], messagesByThread: { g1: [] } });
    await gotoApp(page);
    await seedAgents(page, [EZRI, YEO]);

    // Open the group directly via the store (no CHATS panel overlapping the
    // header), then start the meeting.
    await openGroupChat(page, 'ezri', group);
    await expect(page.getByTestId('group-chat-header')).toBeVisible();

    // Start the meeting -> PATCH meeting_active true -> MeetingView mounts.
    await page.getByTestId('meeting-toggle').click();

    await expect(page.getByTestId('meeting-view')).toBeVisible();
    await expect(page.getByTestId('captain-slot')).toBeVisible();
    await expect(page.getByTestId('avatar-slot-ezri')).toBeVisible();
    await expect(page.getByTestId('avatar-slot-yeo')).toBeVisible();
    // No camera/screen stream in the harness -> the icon fallback renders.
    await expect(page.getByTestId('captain-icon')).toBeVisible();
  });
});
