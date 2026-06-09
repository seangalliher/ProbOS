// AD-941 Issue 3 — "Add people" on a fresh/empty 1:1 must mint a GROUP
// containing BOTH the host and the picked crew (the Captain-reported bug was a
// chat created with only one of them). Encodes the create payload AND the
// resulting opened view (a group header with both avatars, not a 1:1).
import { test, expect } from '@playwright/test';
import { EZRI, YEO, KIRA, JADZIA, mkThread, mockChatApi, gotoApp, seedAgents, openEmptyOneToOne } from './_helpers';

test.describe('AD-941 Issue 3 — Add people mints a group with BOTH crew', () => {
  test('picks Ezri+Yeo, POSTs both participants, opens the group (not a 1:1)', async ({ page }) => {
    const created = mkThread('g2', 'Ezri, Yeo', ['ezri', 'yeo']);
    await mockChatApi(page, { threads: [], createdThread: created, messagesByThread: { g2: [] } });
    await gotoApp(page);
    await seedAgents(page, [EZRI, YEO, KIRA, JADZIA]);

    // Open Ezri's empty 1:1 (no thread yet) -> EmptyChatAddPeople is shown.
    await openEmptyOneToOne(page, 'ezri');
    await page.getByTestId('empty-chat-add-people').click();

    // The seeded picker opens with Ezri locked as the host.
    await expect(page.getByTestId('new-chat-modal')).toBeVisible();
    await expect(page.getByTestId('new-chat-seed-ezri')).toBeVisible();

    // Add Yeo via the picker (filter to narrow to a single row, then click it).
    await page.getByTestId('add-participant-filter').fill('Yeo');
    await page.getByTestId('add-participant-row').click();

    // Confirm -> POST /api/threads must carry BOTH ezri + yeo.
    const [createReq] = await Promise.all([
      page.waitForRequest((r) => new URL(r.url()).pathname === '/api/threads' && r.method() === 'POST'),
      page.getByTestId('new-chat-start').click(),
    ]);
    const body = createReq.postDataJSON() as { participants?: string[] };
    expect(body.participants).toContain('ezri');
    expect(body.participants).toContain('yeo');

    // The opened view is the new GROUP — its header shows BOTH avatars.
    await expect(page.getByTestId('group-chat-header')).toBeVisible();
    await expect(page.getByTestId('group-chat-header').getByLabel('Agent Ezri')).toBeVisible();
    await expect(page.getByTestId('group-chat-header').getByLabel('Agent Yeo')).toBeVisible();
  });
});
