/**
 * AD-520: SpatialExplorerToggle tests.
 */
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { useStore } from '../store/useStore';

// Toggle is defined inline in App.tsx; re-implement the same logic for the unit test
// (mirrors NotebooksToggle test pattern in NotebooksPanel.test.tsx).
function SpatialExplorerToggle() {
  const open = useStore(s => s.spatialExplorerOpen);
  const openExplorer = useStore(s => s.openSpatialExplorer);
  if (open) return null;
  return (
    <div onClick={() => openExplorer()} data-testid="spatial-explorer-toggle">EXPLORER</div>
  );
}

function reset() {
  useStore.setState({
    spatialExplorerOpen: false,
    spatialSelectedNode: null,
    spatialGraphData: null,
    spatialLayoutData: null,
  });
}

describe('SpatialExplorerToggle (AD-520)', () => {
  beforeEach(reset);
  afterEach(() => { cleanup(); reset(); });

  it('is visible when panel is closed', () => {
    render(<SpatialExplorerToggle />);
    expect(screen.getByTestId('spatial-explorer-toggle')).toBeTruthy();
  });

  it('click invokes openSpatialExplorer; toggle hidden when open=true', () => {
    render(<SpatialExplorerToggle />);
    fireEvent.click(screen.getByTestId('spatial-explorer-toggle'));
    expect(useStore.getState().spatialExplorerOpen).toBe(true);
    cleanup();
    render(<SpatialExplorerToggle />);
    expect(screen.queryByTestId('spatial-explorer-toggle')).toBeNull();
  });
});
