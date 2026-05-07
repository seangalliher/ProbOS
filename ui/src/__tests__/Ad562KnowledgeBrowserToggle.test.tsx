/**
 * AD-562: KnowledgeBrowserToggle tests (the App.tsx-defined toggle component).
 *
 * App.tsx defines KnowledgeBrowserToggle inline; we re-create a minimal
 * test-host that mirrors it via the public store API to verify the
 * open/closed visibility contract.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react';
import { useStore } from '../store/useStore';

function Toggle() {
  const open = useStore(s => s.knowledgeBrowserOpen);
  const openBrowser = useStore(s => s.openKnowledgeBrowser);
  if (open) return null;
  return (
    <div data-testid="knowledge-browser-toggle" onClick={() => { void openBrowser(); }}>
      RECORDS
    </div>
  );
}

function reset() {
  useStore.setState({ knowledgeBrowserOpen: false });
}

describe('KnowledgeBrowserToggle (AD-562)', () => {
  beforeEach(reset);
  afterEach(() => { cleanup(); vi.restoreAllMocks(); reset(); });

  it('renders RECORDS label when closed', () => {
    render(<Toggle />);
    const el = screen.getByTestId('knowledge-browser-toggle');
    expect(el.textContent).toBe('RECORDS');
  });

  it('hides itself when knowledgeBrowserOpen=true', () => {
    useStore.setState({ knowledgeBrowserOpen: true });
    render(<Toggle />);
    expect(screen.queryByTestId('knowledge-browser-toggle')).toBeNull();
  });

  it('clicking opens the browser via store action', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({ ok: true, json: async () => ({ documents: [] }) } as Response);
    render(<Toggle />);
    await act(async () => {
      fireEvent.click(screen.getByTestId('knowledge-browser-toggle'));
    });
    expect(useStore.getState().knowledgeBrowserOpen).toBe(true);
  });
});
