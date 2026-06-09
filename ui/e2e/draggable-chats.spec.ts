// AD-941 Issue 1 — the CHATS panel must be draggable (AD-940) so the Captain
// can move it out of the way of an open chat window. Dragging the header moves
// the panel's fixed position by the drag delta.
import { test, expect } from '@playwright/test';
import { mockChatApi, gotoApp, openChats } from './_helpers';

test.describe('AD-941 Issue 1 — the CHATS panel is draggable', () => {
  test('dragging the header moves the panel by the drag delta', async ({ page }) => {
    await mockChatApi(page, { threads: [] });
    await gotoApp(page);
    await openChats(page);

    const panel = page.getByTestId('chats-panel');
    await expect(panel).toBeVisible();
    const before = await panel.boundingBox();
    expect(before).not.toBeNull();

    const handle = page.getByTestId('chats-drag-handle');
    const hb = await handle.boundingBox();
    expect(hb).not.toBeNull();

    // Drag the header by +160 / +130 (two steps so the window mousemove handler
    // fires intermediate updates).
    const startX = hb!.x + hb!.width / 2;
    const startY = hb!.y + hb!.height / 2;
    await page.mouse.move(startX, startY);
    await page.mouse.down();
    await page.mouse.move(startX + 80, startY + 65);
    await page.mouse.move(startX + 160, startY + 130);
    await page.mouse.up();

    const after = await panel.boundingBox();
    expect(after).not.toBeNull();
    // The panel moved by ~the drag delta (allow slack for sub-pixel rounding).
    expect(after!.x).toBeGreaterThan(before!.x + 140);
    expect(after!.y).toBeGreaterThan(before!.y + 110);
  });
});
