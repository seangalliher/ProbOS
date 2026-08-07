/**
 * BF-725 (#1173): the Bridge station rows must be operable from a keyboard.
 *
 * BF-724 made the approvals route reachable and deliberately left this — the
 * finding named three controls and `StationActionRow` was not among them. It is
 * the same defect one scope-line away, and it renders EVERY station launch row
 * (Ward Room, Chats, Crew, Notebooks, Records, Explorer…), so the whole command
 * surface below the approvals section was mouse-only.
 *
 * These tests drive the keyboard and never use `fireEvent.click`. Every
 * pre-BF-724 reachability test in this repo used a click, which is exactly why
 * none of this was caught: clicking a `div` with an onClick passes whether or
 * not the element is focusable, so the assertion proves the handler is wired
 * and says nothing about whether a human without a mouse can get to it.
 *
 * Every section is `defaultOpen: false`, so a station row does not exist until
 * its section is expanded. That makes the honest test the full path — open a
 * section by keyboard, then reach a row by keyboard — which is what a keyboard
 * user actually has to do.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { BridgePanel } from '../BridgePanel';

beforeEach(() => {
  vi.restoreAllMocks();
});

/** The panel as the Bridge mounts it. `open` and `onClose` are required props;
 *  a bare `<BridgePanel />` type-checks as `{}` and `tsc -b` rejects it even
 *  though the tests pass at runtime — which is why both UI gates are run. */
const renderPanel = () => render(<BridgePanel open={true} onClose={() => {}} />);

/**
 * Elements matching `pred`, in DOM order.
 *
 * `querySelectorAll('*')` + a predicate rather than a comma-separated selector
 * list: under jsdom the list form does NOT return document order. Measured
 * during BF-724, where a focus trap built on the list form wrapped Tab onto the
 * wrong element. Tab order is the entire subject here, so the walk has to be
 * the ordered one.
 */
function inDomOrder(
  container: HTMLElement,
  pred: (el: Element) => boolean,
): HTMLElement[] {
  return Array.from(container.querySelectorAll('*')).filter(
    (el): el is HTMLElement => el instanceof HTMLElement && pred(el),
  );
}

const sectionHeaders = (c: HTMLElement) =>
  inDomOrder(c, el => el.tagName === 'BUTTON' && el.hasAttribute('aria-expanded'));

/** Station rows: buttons carrying a testid, excluding the section headers. */
const stationRows = (c: HTMLElement) =>
  inDomOrder(
    c,
    el =>
      el.tagName === 'BUTTON' &&
      el.hasAttribute('data-testid') &&
      !el.hasAttribute('aria-expanded'),
  );

/** Open the first collapsed section using the keyboard only. */
async function openFirstSection(container: HTMLElement) {
  const user = userEvent.setup();
  const header = sectionHeaders(container)[0];
  expect(header).toBeTruthy();
  header.focus();
  await user.keyboard('{Enter}');
  expect(header.getAttribute('aria-expanded')).toBe('true');
  return user;
}

describe('BF-725 the station rows are reachable without a mouse', () => {
  it('renders each station row as a focusable button, not a div', async () => {
    const { container } = renderPanel();
    await openFirstSection(container);

    const rows = stationRows(container);
    expect(rows.length).toBeGreaterThan(0);
    for (const row of rows) {
      expect(row.tagName).toBe('BUTTON');
      // A button is focusable by default; assert it, because tabIndex={-1}
      // would silently take it back out of the tab order.
      expect(row.getAttribute('tabindex')).not.toBe('-1');
    }
  });

  it('reaches a station row by tabbing on from the section header', async () => {
    const { container } = renderPanel();
    const user = await openFirstSection(container);

    const target = stationRows(container)[0];
    // Walk the real tab order rather than calling .focus(): focusing directly
    // would prove the handler works while leaving reachability — the actual
    // defect — untested.
    let guard = 0;
    while (document.activeElement !== target && guard < 40) {
      await user.tab();
      guard += 1;
    }
    expect(document.activeElement).toBe(target);
  });

  it('activates with Enter and with Space, per native button behaviour', async () => {
    const user = userEvent.setup();
    const { container } = renderPanel();
    await openFirstSection(container);

    const row = stationRows(container)[0];
    const onActivate = vi.fn();
    row.addEventListener('click', onActivate);

    row.focus();
    await user.keyboard('{Enter}');
    await user.keyboard(' ');

    // Two activations, one per key. A div with an onClick scores zero here.
    expect(onActivate).toHaveBeenCalledTimes(2);
  });

  it('gives each row an accessible name that says where it goes', async () => {
    const { container } = renderPanel();
    await openFirstSection(container);

    for (const row of stationRows(container)) {
      expect(row.getAttribute('aria-label') ?? '').toMatch(/^Open .+/);
    }
  });

  it('keeps a count badge from running into the destination name', async () => {
    // The badge is decoration on top of the destination. It belongs in the name
    // as a parenthetical so a reader says "Open Chats (3)", not "Open Chats3".
    const { container } = renderPanel();
    await openFirstSection(container);

    for (const row of stationRows(container)) {
      expect(row.getAttribute('aria-label') ?? '').not.toMatch(/\w\d+$/);
    }
  });

  it('carries the shared focus hook, so the amber ring applies and not the UA ring', async () => {
    // HXI #3: the default focus ring breaks the visual language. The rule is
    // attribute-keyed and injected once, so a control opts in by carrying the
    // attribute — a converted control that forgets it silently gets the UA ring.
    const { container } = renderPanel();
    await openFirstSection(container);

    for (const row of stationRows(container)) {
      expect(row.hasAttribute('data-hxi-focus')).toBe(true);
    }
  });

  it('sets border-box, so the converted row is not wider than the div it replaced', async () => {
    // This app has no global `box-sizing: border-box`. `width:100%` plus the
    // 6px side padding renders 12px wider without this — measured during BF-724
    // on the approval row, and caught before hand-off.
    const { container } = renderPanel();
    await openFirstSection(container);

    for (const row of stationRows(container)) {
      expect(row.style.boxSizing).toBe('border-box');
    }
  });

  it('inherits the panel font rather than dropping to the UA default', async () => {
    // A <button> does not inherit font-family. Without the explicit reset every
    // converted control silently leaves the panel's typeface — the change that
    // is easiest to ship and hardest to spot in a diff.
    const { container } = renderPanel();
    await openFirstSection(container);

    for (const row of stationRows(container)) {
      expect(row.style.fontFamily).toBe('inherit');
    }
  });
});
