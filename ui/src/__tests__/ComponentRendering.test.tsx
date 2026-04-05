/**
 * BF-042: Component rendering tests — first @testing-library/react usage.
 *
 * Covers: ScanLineOverlay, BriefingCard, ViewSwitcher, WelcomeOverlay, AgentTooltip.
 */
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { renderWithStore } from '../test/renderHelpers';
import { ScanLineOverlay } from '../components/glass/ScanLineOverlay';
import { BriefingCard } from '../components/glass/BriefingCard';
import { ViewSwitcher } from '../components/ViewSwitcher';
import { WelcomeOverlay } from '../components/WelcomeOverlay';
import { AgentTooltip } from '../components/AgentTooltip';
import { useStore } from '../store/useStore';
import type { Agent } from '../store/types';

// ---------- ScanLineOverlay ----------

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

// ---------- BriefingCard ----------

describe('BriefingCard', () => {
  const defaultProps = {
    completedCount: 3,
    newNotifCount: 2,
    bridgeState: 'idle' as const,
    onDismiss: vi.fn(),
  };

  beforeEach(() => {
    defaultProps.onDismiss = vi.fn();
  });

  it('renders with data-testid', () => {
    render(<BriefingCard {...defaultProps} />);
    expect(screen.getByTestId('briefing-card')).toBeInTheDocument();
  });

  it('shows completed task count (plural)', () => {
    render(<BriefingCard {...defaultProps} />);
    expect(screen.getByText(/3 tasks completed/)).toBeInTheDocument();
  });

  it('shows notification count (plural)', () => {
    render(<BriefingCard {...defaultProps} />);
    expect(screen.getByText(/2 new notifications/)).toBeInTheDocument();
  });

  it('shows bridge state idle', () => {
    render(<BriefingCard {...defaultProps} />);
    expect(screen.getByText(/Bridge: Idle/)).toBeInTheDocument();
  });

  it('shows bridge state attention', () => {
    render(<BriefingCard {...defaultProps} bridgeState="attention" />);
    expect(screen.getByText(/Bridge: Attention Required/)).toBeInTheDocument();
  });

  it('calls onDismiss when clicked', () => {
    render(<BriefingCard {...defaultProps} />);
    fireEvent.click(screen.getByTestId('briefing-card'));
    expect(defaultProps.onDismiss).toHaveBeenCalledOnce();
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

// ---------- ViewSwitcher ----------

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

  it('highlights the active tab with amber color', () => {
    renderWithStore(<ViewSwitcher />, { mainViewer: 'system' });
    const systemBtn = screen.getByText('SYSTEM');
    expect(systemBtn.style.color).toBe('rgb(240, 176, 96)');
  });

  it('switches mainViewer on tab click', () => {
    renderWithStore(<ViewSwitcher />, { mainViewer: 'kanban' });
    fireEvent.click(screen.getByText('SYSTEM'));
    expect(useStore.getState().mainViewer).toBe('system');
  });
});

// ---------- WelcomeOverlay ----------

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
    // The outer div wraps everything — click the overlay backdrop
    const outerOverlay = screen.getByText('Welcome to ProbOS').closest('div[style]')!.parentElement!;
    fireEvent.click(outerOverlay);
    expect(useStore.getState().showIntro).toBe(false);
  });

  it('does NOT dismiss when clicking inside the card', () => {
    renderWithStore(<WelcomeOverlay />, { showIntro: true });
    // Click on heading text inside the card — stopPropagation prevents dismiss
    fireEvent.click(screen.getByText('Welcome to ProbOS'));
    expect(useStore.getState().showIntro).toBe(true);
  });
});

// ---------- AgentTooltip ----------

const MOCK_AGENT: Agent = {
  id: 'agent-001',
  pool: 'engineering',
  callsign: 'LaForge',
  displayName: 'EngineeringAgent',
  agentType: 'EngineeringAgent',
  trust: 0.85,
  confidence: 0.72,
  state: 'active',
  tier: 'domain',
  isCrew: true,
  position: [0, 0, 0],
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
      hoveredAgent: MOCK_AGENT,
      activeProfileAgent: 'agent-001',
      tooltipPos: { x: 100, y: 100 },
    });
    expect(container.firstChild).toBeNull();
  });

  it('shows agent callsign and display name on hover', () => {
    renderWithStore(<AgentTooltip />, {
      hoveredAgent: MOCK_AGENT,
      pinnedAgent: null,
      activeProfileAgent: null,
      tooltipPos: { x: 100, y: 100 },
      poolToGroup: { engineering: 'engineering' },
    });
    expect(screen.getByText('LaForge (EngineeringAgent)')).toBeInTheDocument();
  });

  it('shows trust percentage and high label', () => {
    renderWithStore(<AgentTooltip />, {
      hoveredAgent: MOCK_AGENT,
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
      hoveredAgent: MOCK_AGENT,
      pinnedAgent: null,
      activeProfileAgent: null,
      tooltipPos: { x: 100, y: 100 },
      poolToGroup: {},
    });
    expect(screen.getByText('active')).toBeInTheDocument();
  });

  it('shows medium trust label for mid-range trust', () => {
    const medAgent: Agent = { ...MOCK_AGENT, trust: 0.5 };
    renderWithStore(<AgentTooltip />, {
      hoveredAgent: medAgent,
      pinnedAgent: null,
      activeProfileAgent: null,
      tooltipPos: { x: 100, y: 100 },
      poolToGroup: {},
    });
    expect(screen.getByText('50%')).toBeInTheDocument();
    expect(screen.getByText('(medium)')).toBeInTheDocument();
  });
});
