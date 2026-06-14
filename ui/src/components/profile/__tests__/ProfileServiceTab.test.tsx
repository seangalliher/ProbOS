// AD-1000c + AD-1002: ProfileServiceTab — the per-agent Service Configuration
// tab. Hosts the CapabilityPanel (Tools / Skills / Capabilities) + the read-only
// Instructions + Model sections. Uses the deps passthrough so the test stays
// hermetic (no global fetch mock). HXI #3 (no emoji) is asserted.
import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, cleanup, waitFor } from '@testing-library/react';
import { ProfileServiceTab, type AgentInstructions } from '../ProfileServiceTab';

afterEach(cleanup);

const EMOJI = /\p{Extended_Pictographic}/u;

function caps() {
  return {
    tools: [{ id: 'file_reader', name: 'File Reader', granted: true, source: 'role_default', origin: 'built_in' }],
    skills: [{ id: 'summarize', name: 'Summarize', granted: true, source: 'grant' }],
    mesh_intents: [
      { id: 'run_python', name: 'run_python', description: 'Run a script', requires_consensus: true, tier: 'core', origin: 'built_in', reachable: true },
    ],
  };
}

function instr(): AgentInstructions {
  return {
    agent_type: 'diagnostician',
    department: 'medical',
    instructions: { present: true, char_count: 120, preview: 'You are the diagnostician.' },
    standing_order_tiers: [
      { tier: 'federation', source_file: 'federation.md', present: true, char_count: 800 },
      { tier: 'ship', source_file: 'ship.md', present: true, char_count: 400 },
      { tier: 'department', source_file: 'medical.md', present: true, char_count: 300 },
      { tier: 'agent', source_file: 'diagnostician.md', present: false, char_count: 0 },
    ],
    model: { resolved_tier: 'deep', available_tiers: ['fast', 'standard', 'deep'], note: 'Configured in Settings -> LLM Tiers.' },
  };
}

function deps() {
  return {
    fetchCapabilities: vi.fn(async () => caps()),
    fetchInstructions: vi.fn(async () => instr()),
  };
}

describe('AD-1000c ProfileServiceTab', () => {
  it('renders the Service Configuration heading + the capability panel', async () => {
    render(<ProfileServiceTab agentId="ezri" deps={deps()} />);
    expect(screen.getByTestId('profile-service-tab').textContent).toContain('SERVICE CONFIGURATION');
    await waitFor(() => expect(screen.getByTestId('capability-panel')).toBeTruthy());
    const panel = screen.getByTestId('capability-panel');
    expect(panel.textContent).toContain('TOOLS (1)');
    expect(panel.textContent).toContain('SKILLS (1)');
    // AD-1006: the single fixture intent carries no served flag -> CAN REQUEST.
    expect(panel.textContent).toContain('CAPABILITIES — CAN REQUEST (1)');
  });

  it('forwards the agentId to the capability fetch', async () => {
    const d = deps();
    render(<ProfileServiceTab agentId="yeo" deps={d} />);
    await waitFor(() => expect(d.fetchCapabilities).toHaveBeenCalledWith('yeo'));
  });

  it('uses NO emoji (HXI #3)', async () => {
    const { container } = render(<ProfileServiceTab agentId="ezri" deps={deps()} />);
    await waitFor(() => screen.getByTestId('capability-panel'));
    await waitFor(() => screen.getByTestId('instructions-section'));
    expect(EMOJI.test(container.textContent ?? '')).toBe(false);
  });
});

describe('AD-1002 Instructions + Model sections', () => {
  it('renders the four standing-order tiers with char counts', async () => {
    render(<ProfileServiceTab agentId="bones" deps={deps()} />);
    await waitFor(() => screen.getByTestId('instructions-section'));
    const sec = screen.getByTestId('instructions-section');
    expect(sec.textContent).toContain('INSTRUCTIONS');
    expect(screen.getByTestId('instr-tier-federation').textContent).toContain('800 chars');
    expect(screen.getByTestId('instr-tier-ship')).toBeTruthy();
    expect(screen.getByTestId('instr-tier-department').textContent).toContain('medical.md');
    // absent personal tier shows "none"
    expect(screen.getByTestId('instr-tier-agent').textContent).toContain('none');
  });

  it('renders the resolved model tier + available tiers', async () => {
    render(<ProfileServiceTab agentId="bones" deps={deps()} />);
    await waitFor(() => screen.getByTestId('model-resolved'));
    expect(screen.getByTestId('model-resolved').textContent).toContain('deep');
    const sec = screen.getByTestId('instructions-section');
    expect(sec.textContent).toContain('MODEL');
    expect(sec.textContent).toContain('fast · standard · deep');
  });

  it('forwards agentId to the instructions fetch', async () => {
    const d = deps();
    render(<ProfileServiceTab agentId="bones" deps={d} />);
    await waitFor(() => expect(d.fetchInstructions).toHaveBeenCalledWith('bones'));
  });

  it('shows an error state when the instructions fetch fails', async () => {
    const d = { fetchCapabilities: vi.fn(async () => caps()), fetchInstructions: vi.fn(async () => { throw new Error('boom'); }) };
    render(<ProfileServiceTab agentId="bones" deps={d} />);
    await waitFor(() => expect(screen.getByTestId('instructions-error')).toBeTruthy());
  });
});
