/** AD-841 v1 vitest — DesktopConsole.
 *
 * Deps-injected fetchImpl (no global stub). Verifies the enabled/active readout
 * renders all rows with the configured values, the `enabled:false` payload
 * renders the calm "Off" state (off IS informative — it does NOT self-gate), a
 * hard fetch failure / no-data response self-gates to nothing, and the HXI
 * no-emoji guard holds.
 */
import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, cleanup, waitFor } from '@testing-library/react';
import DesktopConsole from './DesktopConsole';

const EMOJI = /\p{Extended_Pictographic}/u;

const ON = {
  enabled: true,
  active: true,
  tray: { active: true, autostart: true },
  hotkey: { active: true, binding: 'ctrl+shift+space' },
  notifications: { active: true, timeout_sec: 5 },
  quiet_hours: { start: '19:00', end: '08:00' },
  autostart_enabled: false,
  lock: { name: 'yeo.lock', present: true },
};

const OFF = {
  enabled: false,
  active: false,
  tray: { active: false, autostart: true },
  hotkey: { active: false, binding: 'ctrl+shift+space' },
  notifications: { active: false, timeout_sec: 5 },
  quiet_hours: { start: '19:00', end: '08:00' },
  autostart_enabled: false,
  lock: { name: 'yeo.lock', present: false },
};

function res(body: unknown, ok = true, status = 200) {
  return { ok, status, json: async () => body } as Response;
}

function fetchReturning(body: unknown) {
  return vi.fn(() => Promise.resolve(res(body)));
}

describe('DesktopConsole (AD-841)', () => {
  afterEach(() => cleanup());

  it('renders_enabled_active_status', async () => {
    const fm = fetchReturning(ON);
    render(<DesktopConsole fetchImpl={fm as unknown as typeof fetch} />);
    await waitFor(() => expect(screen.getByTestId('desktop-console')).toBeTruthy());
    expect(screen.getByTestId('desktop-row-active').textContent).toContain('Wired');
    expect(screen.getByTestId('desktop-row-hotkey').textContent).toContain('ctrl+shift+space');
    expect(screen.getByTestId('desktop-row-notifications').textContent).toContain('5s');
    expect(screen.getByTestId('desktop-row-lock').textContent).toContain('yeo.lock');
    expect(screen.getByTestId('desktop-row-lock').textContent).toContain('present');
  });

  it('renders_calm_off_state', async () => {
    const fm = fetchReturning(OFF);
    render(<DesktopConsole fetchImpl={fm as unknown as typeof fetch} />);
    await waitFor(() => expect(screen.getByTestId('desktop-console')).toBeTruthy());
    expect(screen.getByTestId('desktop-off').textContent).toContain('Off');
    // The calm Off readout omits the detail rows.
    expect(screen.queryByTestId('desktop-row-active')).toBeNull();
  });

  it('self_gates_when_fetch_rejects', async () => {
    const fm = vi.fn(() => Promise.reject(new Error('network down')));
    const { container } = render(<DesktopConsole fetchImpl={fm as unknown as typeof fetch} />);
    await waitFor(() => {
      expect(fm).toHaveBeenCalled();
      expect(container.querySelector('[data-testid="desktop-console"]')).toBeNull();
    });
  });

  it('self_gates_when_no_data', async () => {
    const fm = vi.fn(() => Promise.resolve(res(null)));
    const { container } = render(<DesktopConsole fetchImpl={fm as unknown as typeof fetch} />);
    await waitFor(() => {
      expect(fm).toHaveBeenCalled();
      expect(container.querySelector('[data-testid="desktop-console"]')).toBeNull();
    });
  });

  it('contains_no_emoji_glyphs', async () => {
    const fm = fetchReturning(ON);
    const { container } = render(<DesktopConsole fetchImpl={fm as unknown as typeof fetch} />);
    await waitFor(() => expect(screen.getByTestId('desktop-console')).toBeTruthy());
    expect(EMOJI.test(container.innerHTML)).toBe(false);
  });
});
