// AD-1000c: ProfileServiceTab — the per-agent Service Configuration tab.
// Hosts the CapabilityPanel (Tools / Skills / Capabilities). Uses the deps
// passthrough so the test stays hermetic (no global fetch mock). HXI #3 (no
// emoji) is asserted.
import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, cleanup, waitFor } from '@testing-library/react';
import { ProfileServiceTab } from '../ProfileServiceTab';

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

describe('AD-1000c ProfileServiceTab', () => {
  it('renders the Service Configuration heading + the capability panel', async () => {
    const fetchCapabilities = vi.fn(async () => caps());
    render(<ProfileServiceTab agentId="ezri" deps={{ fetchCapabilities }} />);
    expect(screen.getByTestId('profile-service-tab').textContent).toContain('SERVICE CONFIGURATION');
    await waitFor(() => expect(screen.getByTestId('capability-panel')).toBeTruthy());
    // The three axes render through the hosted CapabilityPanel.
    const panel = screen.getByTestId('capability-panel');
    expect(panel.textContent).toContain('TOOLS (1)');
    expect(panel.textContent).toContain('SKILLS (1)');
    expect(panel.textContent).toContain('CAPABILITIES (1)');
  });

  it('forwards the agentId to the capability fetch', async () => {
    const fetchCapabilities = vi.fn(async () => caps());
    render(<ProfileServiceTab agentId="yeo" deps={{ fetchCapabilities }} />);
    await waitFor(() => expect(fetchCapabilities).toHaveBeenCalledWith('yeo'));
  });

  it('uses NO emoji (HXI #3)', async () => {
    const fetchCapabilities = vi.fn(async () => caps());
    const { container } = render(<ProfileServiceTab agentId="ezri" deps={{ fetchCapabilities }} />);
    await waitFor(() => screen.getByTestId('capability-panel'));
    expect(EMOJI.test(container.textContent ?? '')).toBe(false);
  });
});
