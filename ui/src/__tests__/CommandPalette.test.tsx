// AD-946: presentational tests for the command-palette listbox. Props-only,
// no store coupling (nav state lives on the IntentSurface host).
import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, cleanup, fireEvent } from '@testing-library/react';
import { CommandPalette } from '../components/CommandPalette';
import type { PaletteCommand } from '../components/bridge/paletteCommands';

// HXI #3 — stroke-SVG glyphs only, never emoji.
const EMOJI_RE = /[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}]/u;

function makeCommands(): PaletteCommand[] {
  return [
    { id: 'operations:expand', label: 'Work Board', station: 'Operations', run: vi.fn() },
    { id: 'ward-room-action', label: 'Ward Room', station: 'Communications', run: vi.fn() },
  ];
}

afterEach(() => {
  cleanup();
});

describe('AD-946 CommandPalette', () => {
  it('renders a listbox with one option per match and marks the active row', () => {
    render(
      <CommandPalette matches={makeCommands()} activeIndex={0} onHover={() => {}} onRun={() => {}} />,
    );
    expect(screen.getByRole('listbox')).toBeTruthy();
    const options = screen.getAllByRole('option');
    expect(options.length).toBe(2);
    expect(options[0].getAttribute('aria-selected')).toBe('true');
    expect(options[1].getAttribute('aria-selected')).toBe('false');
    // The label and the dim station tag both render.
    expect(options[0].textContent).toContain('Work Board');
    expect(options[0].textContent).toContain('Operations');
  });

  it('calls onRun with the row command on mousedown (focus-preserving confirm)', () => {
    const cmds = makeCommands();
    const onRun = vi.fn();
    render(<CommandPalette matches={cmds} activeIndex={0} onHover={() => {}} onRun={onRun} />);
    const options = screen.getAllByRole('option');
    fireEvent.mouseDown(options[1]);
    expect(onRun).toHaveBeenCalledTimes(1);
    expect(onRun).toHaveBeenCalledWith(cmds[1]);
  });

  it('reports hover to onHover with the row index', () => {
    const onHover = vi.fn();
    render(<CommandPalette matches={makeCommands()} activeIndex={0} onHover={onHover} onRun={() => {}} />);
    const options = screen.getAllByRole('option');
    fireEvent.mouseEnter(options[1]);
    expect(onHover).toHaveBeenCalledWith(1);
  });

  it('renders a stroke-SVG ChevronRight glyph per row and no emoji (HXI #3)', () => {
    const { container } = render(
      <CommandPalette matches={makeCommands()} activeIndex={0} onHover={() => {}} onRun={() => {}} />,
    );
    const options = screen.getAllByRole('option');
    for (const opt of options) {
      const svg = opt.querySelector('svg');
      expect(svg).toBeTruthy();
      expect(svg!.getAttribute('stroke')).toBe('currentColor');
    }
    expect(EMOJI_RE.test(container.innerHTML)).toBe(false);
  });

  it('shows an empty state and no option rows when there are no matches', () => {
    render(<CommandPalette matches={[]} activeIndex={0} onHover={() => {}} onRun={() => {}} />);
    expect(screen.getByText('No matching command.')).toBeTruthy();
    expect(screen.queryAllByRole('option').length).toBe(0);
  });
});
