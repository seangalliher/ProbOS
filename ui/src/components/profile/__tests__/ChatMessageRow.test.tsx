// BF-614: ChatMessageRow author resolution. A group fan-out reply can arrive
// with a BLANK callsign (the backend couldn't resolve it for an added
// participant); the row must fall back to the agents-map callsign for the real
// author rather than rendering the empty '?' initial or mis-attributing to the
// host. Real store via setState (BF-287); ChatMessageRow imports only
// useStore + AgentAvatarBadge, so it renders standalone under jsdom.
import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, within, cleanup } from '@testing-library/react';
import { ChatMessageRow } from '../ChatMessageRow';
import { useStore } from '../../../store/useStore';
import type { Agent, AgentProfileMessage } from '../../../store/types';

function mkAgent(p: { id: string; callsign: string; department?: string }): Agent {
  return {
    id: p.id,
    agentType: 'crew',
    callsign: p.callsign,
    displayName: '',
    pool: 'bridge',
    state: 'active',
    confidence: 1,
    trust: 0.5,
    tier: 'domain',
    isCrew: true,
    position: [0, 0, 0] as [number, number, number],
    department: p.department ?? 'science',
  } as unknown as Agent;
}

function seed(agentsList: Agent[]): void {
  const am = new Map<string, Agent>();
  for (const a of agentsList) am.set(a.id, a);
  useStore.setState({ agents: am });
}

function mkMsg(over: Partial<AgentProfileMessage>): AgentProfileMessage {
  return {
    id: over.id ?? 'm1',
    role: over.role ?? 'agent',
    text: over.text ?? 'hello',
    timestamp: over.timestamp ?? 0,
    authorId: over.authorId,
    callsign: over.callsign,
  };
}

afterEach(() => {
  cleanup();
  useStore.setState({ agents: new Map() });
});

describe('BF-614 ChatMessageRow author resolution', () => {
  it("falls back to the agents-map callsign when a group reply's callsign is blank", () => {
    seed([mkAgent({ id: 'yeoman_0', callsign: 'Yeo' })]);
    // The fan-out reply threaded the real authorId but a BLANK callsign.
    render(
      <ChatMessageRow
        msg={mkMsg({ authorId: 'yeoman_0', callsign: '' })}
        hostAgentId="counselor_0"
        hostCallsign="Ezri"
      />,
    );
    const badge = screen.getByTestId('agent-avatar-badge');
    // Resolves to 'Y' (Yeo), NOT the empty '?' and NOT the host 'E' (Ezri).
    expect(badge.textContent).toBe('Y');
    expect(within(badge).queryByText('?')).toBeNull();
  });

  it('uses the explicit reply callsign when present (unchanged)', () => {
    seed([mkAgent({ id: 'yeoman_0', callsign: 'Yeo' })]);
    render(
      <ChatMessageRow
        msg={mkMsg({ authorId: 'yeoman_0', callsign: 'Yeoman' })}
        hostAgentId="counselor_0"
        hostCallsign="Ezri"
      />,
    );
    expect(screen.getByTestId('agent-avatar-badge').textContent).toBe('Y');
  });

  it('a legacy/1:1 message with NO authorId falls back to the host callsign', () => {
    seed([mkAgent({ id: 'counselor_0', callsign: 'Ezri' })]);
    render(
      <ChatMessageRow
        msg={mkMsg({ authorId: undefined, callsign: undefined })}
        hostAgentId="counselor_0"
        hostCallsign="Ezri"
      />,
    );
    expect(screen.getByTestId('agent-avatar-badge').textContent).toBe('E');
  });

  it("an unresolved explicit author keeps the honest '?' rather than mis-attributing to the host", () => {
    seed([mkAgent({ id: 'counselor_0', callsign: 'Ezri' })]); // yeoman NOT in the map
    render(
      <ChatMessageRow
        msg={mkMsg({ authorId: 'unknown_99', callsign: '' })}
        hostAgentId="counselor_0"
        hostCallsign="Ezri"
      />,
    );
    // Author can't be resolved and the reply carried an explicit authorId, so
    // the badge stays '?' (honest) instead of falsely showing the host 'E'.
    expect(screen.getByTestId('agent-avatar-badge').textContent).toBe('?');
  });
});
