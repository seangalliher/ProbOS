/**
 * Test helpers for rendering components with Zustand store state (BF-042).
 */
import { render, type RenderOptions } from '@testing-library/react';
import type { ReactElement } from 'react';
import { useStore } from '../store/useStore';

type StoreState = ReturnType<typeof useStore.getState>;

// Snapshot initial state at module load (before any test mutates).
const INITIAL_STATE = useStore.getState();

/**
 * Render a component with pre-set Zustand store state.
 * Resets store to defaults, then merges overrides.
 */
export function renderWithStore(
  ui: ReactElement,
  storeOverrides?: Partial<StoreState>,
  options?: Omit<RenderOptions, 'wrapper'>,
) {
  // Full replace to initial state
  useStore.setState(INITIAL_STATE, true);

  // Apply overrides
  if (storeOverrides) {
    useStore.setState(storeOverrides);
  }

  return render(ui, options);
}
