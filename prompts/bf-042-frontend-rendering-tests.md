# BF-042: Frontend Component Rendering Tests

## Context

The HXI frontend has 29 React components and 10 test files — but **zero component rendering tests**. All 10 existing test files test Zustand store logic or pure functions. `@testing-library/react` and `@testing-library/user-event` are installed in `devDependencies` but never imported. No test calls `render()`.

This AD adds component rendering tests for the highest-value, most testable components. Canvas components (R3F/WebGL) are excluded — they require specialized test infrastructure that is out of scope.

**Working directory:** `d:\ProbOS\ui`

## Step 1: Create test utilities

Create `ui/src/test/renderHelpers.tsx`:

```tsx
/**
 * Test helpers for rendering components with Zustand store state (BF-042).
 */
import { render, type RenderOptions } from '@testing-library/react';
import type { ReactElement } from 'react';
import { useStore } from '../store/useStore';

type StoreState = ReturnType<typeof useStore.getState>;

/**
 * Render a component with pre-set Zustand store state.
 * Resets store to defaults after each call, then merges overrides.
 */
export function renderWithStore(
  ui: ReactElement,
  storeOverrides?: Partial<StoreState>,
  options?: Omit<RenderOptions, 'wrapper'>,
) {
  // Reset store to initial state
  const { getInitialState } = useStore;
  if (getInitialState) {
    useStore.setState(getInitialState(), true);
  }

  // Apply overrides
  if (storeOverrides) {
    useStore.setState(storeOverrides);
  }

  return render(ui, options);
}
```

**IMPORTANT:** Check how Zustand 5's `create()` exposes initial state. If `getInitialState` doesn't exist on the store, use a different approach — e.g., snapshot the initial state at module load time:

```tsx
const INITIAL_STATE = useStore.getState();

export function renderWithStore(...) {
  useStore.setState(INITIAL_STATE, true);  // full replace
  if (storeOverrides) useStore.setState(storeOverrides);
  return render(ui, options);
}
```

Pick whichever approach works with the installed Zustand version.

## Step 2: Component rendering tests

Create `ui/src/__tests__/ComponentRendering.test.tsx`. This single file covers all component rendering tests, grouped by component.

### 2a. ScanLineOverlay — simplest component (props only, no store)

```tsx
import { render, screen } from '@testing-library/react';
import { ScanLineOverlay } from '../components/glass/ScanLineOverlay';

describe('ScanLineOverlay', () => {
  it('renders with data-testid', () => {
    render(<ScanLineOverlay intensity={0.5} />);
    expect(screen.getByTestId('scan-line-overlay')).toBeInTheDocument();
  });

  it('applies opacity based on intensity', () => {
    render(<ScanLineOverlay intensity={1.0} />);
    const el = screen.getByTestId('scan-line-overlay');
    expect(el.style.opacity).toBe('0.8'); // intensity * 0.8
  });

  it('renders with zero intensity', () => {
    render(<ScanLineOverlay intensity={0} />);
    const el = screen.getByTestId('scan-line-overlay');
    expect(el.style.opacity).toBe('0');
  });
});
```

### 2b. BriefingCard — props-only component

```tsx
import { render, screen, fireEvent } from '@testing-library/react';
import { BriefingCard } from '../components/glass/BriefingCard';

describe('BriefingCard', () => {
  const defaultProps = {
    completedCount: 3,
    newNotifCount: 2,
    bridgeState: 'idle' as const,
    onDismiss: vi.fn(),
  };

  it('renders with data-testid', () => {
    render(<BriefingCard {...defaultProps} />);
    expect(screen.getByTestId('briefing-card')).toBeInTheDocument();
  });

  it('shows completed task count', () => {
    render(<BriefingCard {...defaultProps} />);
    expect(screen.getByText(/3 tasks completed/)).toBeInTheDocument();
  });

  it('shows notification count', () => {
    render(<BriefingCard {...defaultProps} />);
    expect(screen.getByText(/2 new notifications/)).toBeInTheDocument();
  });

  it('shows bridge state', () => {
    render(<BriefingCard {...defaultProps} bridgeState="attention" />);
    expect(screen.getByText(/Attention Required/)).toBeInTheDocument();
  });

  it('calls onDismiss when clicked', () => {
    const onDismiss = vi.fn();
    render(<BriefingCard {...defaultProps} onDismiss={onDismiss} />);
    fireEvent.click(screen.getByTestId('briefing-card'));
    expect(onDismiss).toHaveBeenCalledOnce();
  });

  it('uses singular "task" for count of 1', () => {
    render(<BriefingCard {...defaultProps} completedCount={1} />);
    expect(screen.getByText(/1 task completed/)).toBeInTheDocument();
  });

  it('hides completed section when count is 0', () => {
    render(<BriefingCard {...defaultProps} completedCount={0} />);
    expect(screen.queryByText(/task.*completed/)).not.toBeInTheDocument();
  });

  it('hides notification section when count is 0', () => {
    render(<BriefingCard {...defaultProps} newNotifCount={0} />);
    expect(screen.queryByText(/new notification/)).not.toBeInTheDocument();
  });
});
```

### 2c. ViewSwitcher — store-connected, conditional rendering

```tsx
import { screen, fireEvent } from '@testing-library/react';
import { renderWithStore } from '../test/renderHelpers';
import { ViewSwitcher } from '../components/ViewSwitcher';
import { useStore } from '../store/useStore';

describe('ViewSwitcher', () => {
  it('renders nothing when mainViewer is canvas', () => {
    const { container } = renderWithStore(<ViewSwitcher />, { mainViewer: 'canvas' });
    expect(container.firstChild).toBeNull();
  });

  it('renders tab buttons when mainViewer is not canvas', () => {
    renderWithStore(<ViewSwitcher />, { mainViewer: 'kanban' });
    expect(screen.getByText('CANVAS')).toBeInTheDocument();
    expect(screen.getByText('KANBAN')).toBeInTheDocument();
    expect(screen.getByText('SYSTEM')).toBeInTheDocument();
    expect(screen.getByText('WORK')).toBeInTheDocument();
  });

  it('highlights the active tab', () => {
    renderWithStore(<ViewSwitcher />, { mainViewer: 'system' });
    const systemBtn = screen.getByText('SYSTEM');
    // Active tab has amber text color
    expect(systemBtn.style.color).toBe('#f0b060');
  });

  it('switches mainViewer on tab click', () => {
    renderWithStore(<ViewSwitcher />, { mainViewer: 'kanban' });
    fireEvent.click(screen.getByText('SYSTEM'));
    expect(useStore.getState().mainViewer).toBe('system');
  });
});
```

### 2d. WelcomeOverlay — store-connected, dismiss logic

```tsx
import { screen, fireEvent } from '@testing-library/react';
import { renderWithStore } from '../test/renderHelpers';
import { WelcomeOverlay } from '../components/WelcomeOverlay';
import { useStore } from '../store/useStore';

describe('WelcomeOverlay', () => {
  it('renders nothing when showIntro is false', () => {
    const { container } = renderWithStore(<WelcomeOverlay />, { showIntro: false });
    expect(container.firstChild).toBeNull();
  });

  it('renders welcome content when showIntro is true', () => {
    renderWithStore(<WelcomeOverlay />, { showIntro: true });
    expect(screen.getByText('Welcome to ProbOS')).toBeInTheDocument();
    expect(screen.getByText('Got it')).toBeInTheDocument();
  });

  it('dismisses on Got it button click', () => {
    renderWithStore(<WelcomeOverlay />, { showIntro: true });
    fireEvent.click(screen.getByText('Got it'));
    expect(useStore.getState().showIntro).toBe(false);
  });

  it('dismisses on overlay background click', () => {
    renderWithStore(<WelcomeOverlay />, { showIntro: true });
    // Click the outer overlay div (not the inner card)
    const overlay = screen.getByText('Welcome to ProbOS').closest('div')!.parentElement!;
    fireEvent.click(overlay);
    expect(useStore.getState().showIntro).toBe(false);
  });

  it('does NOT dismiss when clicking inside the card', () => {
    renderWithStore(<WelcomeOverlay />, { showIntro: true });
    // Click on the heading text (inside the card)
    fireEvent.click(screen.getByText('Welcome to ProbOS'));
    // showIntro should still be true (stopPropagation on inner div)
    expect(useStore.getState().showIntro).toBe(true);
  });
});
```

### 2e. AgentTooltip — store-connected, conditional rendering with data

NOTE: AgentTooltip reads `hoveredAgent`, `pinnedAgent`, `activeProfileAgent`, `tooltipPos`, `agentTasks`, `poolToGroup` from the store. You'll need to construct a minimal agent object.

```tsx
import { screen } from '@testing-library/react';
import { renderWithStore } from '../test/renderHelpers';
import { AgentTooltip } from '../components/AgentTooltip';

const MOCK_AGENT = {
  id: 'agent-001',
  pool: 'engineering',
  callsign: 'LaForge',
  displayName: 'EngineeringAgent',
  agentType: 'EngineeringAgent',
  trust: 0.85,
  confidence: 0.72,
  state: 'active' as const,
  tier: 'crew',
};

describe('AgentTooltip', () => {
  it('renders nothing when no agent is hovered or pinned', () => {
    const { container } = renderWithStore(<AgentTooltip />, {
      hoveredAgent: null,
      pinnedAgent: null,
    });
    expect(container.firstChild).toBeNull();
  });

  it('renders nothing when profile panel is active', () => {
    const { container } = renderWithStore(<AgentTooltip />, {
      hoveredAgent: MOCK_AGENT as any,
      activeProfileAgent: 'agent-001',
      tooltipPos: { x: 100, y: 100 },
    });
    expect(container.firstChild).toBeNull();
  });

  it('shows agent callsign and display name on hover', () => {
    renderWithStore(<AgentTooltip />, {
      hoveredAgent: MOCK_AGENT as any,
      pinnedAgent: null,
      activeProfileAgent: null,
      tooltipPos: { x: 100, y: 100 },
      poolToGroup: { engineering: 'engineering' },
    });
    expect(screen.getByText('LaForge (EngineeringAgent)')).toBeInTheDocument();
  });

  it('shows trust percentage', () => {
    renderWithStore(<AgentTooltip />, {
      hoveredAgent: MOCK_AGENT as any,
      pinnedAgent: null,
      activeProfileAgent: null,
      tooltipPos: { x: 100, y: 100 },
      poolToGroup: {},
    });
    expect(screen.getByText('85%')).toBeInTheDocument();
    expect(screen.getByText('(high)')).toBeInTheDocument();
  });

  it('shows agent state', () => {
    renderWithStore(<AgentTooltip />, {
      hoveredAgent: MOCK_AGENT as any,
      pinnedAgent: null,
      activeProfileAgent: null,
      tooltipPos: { x: 100, y: 100 },
      poolToGroup: {},
    });
    expect(screen.getByText('active')).toBeInTheDocument();
  });

  it('shows medium trust label for mid-range trust', () => {
    const medAgent = { ...MOCK_AGENT, trust: 0.5 };
    renderWithStore(<AgentTooltip />, {
      hoveredAgent: medAgent as any,
      pinnedAgent: null,
      activeProfileAgent: null,
      tooltipPos: { x: 100, y: 100 },
      poolToGroup: {},
    });
    expect(screen.getByText('(medium)')).toBeInTheDocument();
  });
});
```

**NOTE on `MOCK_AGENT`:** Check what the actual `Agent` type looks like in `ui/src/store/types.ts`. The mock object must match the shape the component reads. If necessary, cast or extend with required fields. Don't import the type if it's just an interface — build a plain object that satisfies the shape.

## Step 3: Run tests

```bash
cd d:\ProbOS\ui
npx vitest run src/__tests__/ComponentRendering.test.tsx --reporter=verbose
```

All tests must pass. Then run the full frontend suite:

```bash
npx vitest run
```

Existing 149 tests must still pass alongside the new rendering tests.

## Critical Rules

1. **Do NOT modify any component code.** This is test-only.
2. **Do NOT test R3F/Canvas components** (`CognitiveCanvas`, `canvas/agents.tsx`, etc.). They require WebGL mocking which is out of scope.
3. **Do NOT test `IntentSurface.tsx`** (81KB, too complex for this pass).
4. **Match existing test conventions** — put tests in `ui/src/__tests__/`, use `vi.fn()` for mocks, use `describe`/`it` blocks.
5. **Use `@testing-library/react`** — it's installed, just unused. This is the whole point of BF-042.
6. **Reset Zustand state between tests** via the `renderWithStore` helper. Zustand is module-scoped, so state leaks between tests without explicit reset.
7. **Minimum: 5 components, 25+ test cases** covering renders-nothing, renders-content, user-interaction, and store-integration patterns.
