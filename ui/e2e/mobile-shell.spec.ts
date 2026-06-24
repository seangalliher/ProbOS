import { test, expect } from '@playwright/test';
import { YEO, mockChatApi, gotoApp, seedAgents } from './_helpers';

test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

test.describe('AD-708b — PADD mobile shell', () => {
  test('a real handheld renders the full-screen mobile chat shell', async ({ page }) => {
    await mockChatApi(page, {});
    await gotoApp(page);
    await seedAgents(page, [YEO]);
    await expect(page.getByTestId('mobile-shell')).toBeVisible();
    await expect(page.getByTestId('mobile-shell-chat')).toBeVisible();
  });

  test('the #desktop escape hatch forces the full HXI even on a handheld', async ({ page }) => {
    await mockChatApi(page, {});
    await page.addInitScript(() => { try { localStorage.setItem('hxi_seen_intro', 'true'); } catch { /* */ } });
    await page.goto('/#desktop');
    await page.waitForFunction(() => Boolean((window as unknown as { __store?: unknown }).__store));
    await expect(page.getByTestId('mobile-shell')).toHaveCount(0);
  });
});
