/** AD-1019d vitest — per-tool risk-tier authoring surface.
 *
 * Consumes the AD-1019e risk endpoints via the `deps` injection (no global
 * fetch mock, no real network). Asserts: the three tier glyphs render, a tier
 * write (PUT setRisk), a reset (DELETE clearRisk), the risk_source badge
 * (override/default), the management-disabled (GET 404) state, and the HXI
 * no-emoji guard.
 */
import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import { McpToolRisk, type McpToolRiskDeps, type McpToolRiskResult } from './McpToolRisk';

const EMOJI = /\p{Extended_Pictographic}/u;

function makeResult(over: Partial<McpToolRiskResult> = {}): McpToolRiskResult {
  return {
    tools: [
      { name: 'echo', description: 'echo a message', risk: 'open', risk_source: 'default' },
      { name: 'deploy', description: 'deploy', risk: 'consensus', risk_source: 'override' },
    ],
    count: 2,
    ...over,
  };
}

function makeDeps(over: Partial<McpToolRiskDeps> = {}): McpToolRiskDeps {
  return {
    fetchTools: vi.fn(async () => makeResult()),
    setRisk: vi.fn(async () => {}),
    clearRisk: vi.fn(async () => {}),
    ...over,
  };
}

function renderPanel(deps: McpToolRiskDeps) {
  return render(<McpToolRisk serverId="srv-1" serverName="github-mcp" deps={deps} />);
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('AD-1019d McpToolRisk', () => {
  it('renders the three risk tiers per tool from the injected fetchTools', async () => {
    const deps = makeDeps();
    renderPanel(deps);
    await waitFor(() => screen.getByTestId('mcp-risk-github-mcp-echo-open'));
    expect(screen.getByTestId('mcp-risk-github-mcp-echo-open')).toBeTruthy();
    expect(screen.getByTestId('mcp-risk-github-mcp-echo-confirm')).toBeTruthy();
    expect(screen.getByTestId('mcp-risk-github-mcp-echo-consensus')).toBeTruthy();
    expect(deps.fetchTools).toHaveBeenCalled();
  });

  it('sets a tool to consensus (PUT setRisk)', async () => {
    const deps = makeDeps();
    renderPanel(deps);
    await waitFor(() => screen.getByTestId('mcp-risk-github-mcp-echo-consensus'));
    fireEvent.click(screen.getByTestId('mcp-risk-github-mcp-echo-consensus'));
    await waitFor(() => expect(deps.setRisk).toHaveBeenCalledWith('echo', 'consensus'));
  });

  it('sets a tool to confirm (PUT setRisk)', async () => {
    const deps = makeDeps();
    renderPanel(deps);
    await waitFor(() => screen.getByTestId('mcp-risk-github-mcp-deploy-confirm'));
    fireEvent.click(screen.getByTestId('mcp-risk-github-mcp-deploy-confirm'));
    await waitFor(() => expect(deps.setRisk).toHaveBeenCalledWith('deploy', 'confirm'));
  });

  it('clears a tool override to default (DELETE clearRisk)', async () => {
    const deps = makeDeps();
    renderPanel(deps);
    await waitFor(() => screen.getByTestId('mcp-risk-reset-github-mcp-echo'));
    fireEvent.click(screen.getByTestId('mcp-risk-reset-github-mcp-echo'));
    await waitFor(() => expect(deps.clearRisk).toHaveBeenCalledWith('echo'));
  });

  it('shows the risk_source badge (override / default)', async () => {
    const deps = makeDeps();
    renderPanel(deps);
    await waitFor(() => screen.getByTestId('mcp-risk-source-github-mcp-echo'));
    expect(screen.getByTestId('mcp-risk-source-github-mcp-echo').textContent).toContain('default');
    expect(screen.getByTestId('mcp-risk-source-github-mcp-deploy').textContent).toContain('override');
  });

  it('shows the management-disabled state on a GET 404 (fetchTools.disabled)', async () => {
    const deps = makeDeps({ fetchTools: vi.fn(async () => ({ tools: [], count: 0, disabled: true })) });
    renderPanel(deps);
    await waitFor(() => expect(screen.getByTestId('mcp-risk-disabled-srv-1')).toBeTruthy());
    expect(screen.getByTestId('mcp-risk-disabled-srv-1').textContent).toContain('MCP management is disabled');
  });

  it('uses NO emoji (HXI #3)', async () => {
    const deps = makeDeps();
    const { container } = renderPanel(deps);
    await waitFor(() => screen.getByTestId('mcp-risk-github-mcp-echo-open'));
    expect(EMOJI.test(container.textContent ?? '')).toBe(false);
    expect(EMOJI.test(container.innerHTML)).toBe(false);
  });
});
