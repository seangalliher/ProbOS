// AD-936: tests for the per-message metadata row (author avatar + callsign +
// HH:MM timestamp) added to the profile chat transcript. The full
// ProfileChatTab is too heavy to render (audio/screen deps — same rationale as
// ProfileChatTab.bf294b/groupsend), so the presentational `ChatMessageRow` is
// extracted and tested directly. Real zustand store via useStore.setState
// (BF-287 real-fixture style, no MagicMock). HXI no-emoji guard included.
import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { useStore } from '../../../store/useStore';
import type { Agent, AgentProfileMessage } from '../../../store/types';
import { ChatMessageRow, formatChatTime } from '../ChatMessageRow';
import rowSource from '../ChatMessageRow?raw';

const EMOJI_RE = /\p{Extended_Pictographic}/u;

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
    department: p.department ?? '',
  } as Agent;
}

function seedAgents(list: Agent[]): void {
  const m = new Map<string, Agent>();
  for (const a of list) m.set(a.id, a);
  useStore.setState({ agents: m });
}

function mkMsg(p: Partial<AgentProfileMessage> & { id: string; role: AgentProfileMessage['role'] }): AgentProfileMessage {
  return {
    text: p.text ?? 'hello',
    timestamp: p.timestamp ?? 1_700_000_000, // fixed epoch (seconds)
    ...p,
  } as AgentProfileMessage;
}

afterEach(() => {
  cleanup();
  useStore.setState({ agents: new Map(), agentConversations: new Map() });
});

describe('AD-936 ChatMessageRow metadata', () => {
  it('renders an avatar, callsign label, and HH:MM timestamp for an agent message', () => {
    seedAgents([mkAgent({ id: 'a1', callsign: 'Aria', department: 'science' })]);
    render(
      <ChatMessageRow
        msg={mkMsg({ id: 'm1', role: 'agent', authorId: 'a1', callsign: 'Aria', text: 'status nominal' })}
        hostAgentId="a1"
        hostCallsign="Aria"
      />,
    );
    const badge = screen.getByTestId('agent-avatar-badge');
    expect(badge.textContent).toBe('A'); // first letter of callsign
    expect(screen.getByText('Aria')).toBeTruthy(); // name label
    expect(screen.getByTestId('chat-msg-time').textContent).toMatch(/\d{1,2}:\d{2}/);
  });

  it('renders two DISTINCT avatars for two group replies from different authors', () => {
    seedAgents([
      mkAgent({ id: 'a1', callsign: 'Aria', department: 'science' }),
      mkAgent({ id: 'a2', callsign: 'Lume', department: 'engineering' }),
    ]);
    render(
      <>
        <ChatMessageRow
          msg={mkMsg({ id: 'm1', role: 'agent', authorId: 'a1', callsign: 'Aria' })}
          hostAgentId="a1"
          hostCallsign="Aria"
        />
        <ChatMessageRow
          msg={mkMsg({ id: 'm2', role: 'agent', authorId: 'a2', callsign: 'Lume' })}
          hostAgentId="a1"
          hostCallsign="Aria"
        />
      </>,
    );
    const badges = screen.getAllByTestId('agent-avatar-badge');
    expect(badges).toHaveLength(2);
    const initials = badges.map((b) => b.textContent);
    expect(initials).toContain('A');
    expect(initials).toContain('L');
    expect(initials[0]).not.toBe(initials[1]);
  });

  it('falls back to the host avatar when the message has no authorId (1:1 / legacy)', () => {
    seedAgents([mkAgent({ id: 'host', callsign: 'Nova', department: 'medical' })]);
    render(
      <ChatMessageRow
        msg={mkMsg({ id: 'm1', role: 'agent', text: 'reply' })}
        hostAgentId="host"
        hostCallsign="Nova"
      />,
    );
    const badge = screen.getByTestId('agent-avatar-badge');
    expect(badge.textContent).toBe('N'); // host callsign initial
    expect(screen.getByText('Nova')).toBeTruthy();
  });

  it('renders a timestamp and NO avatar for a user (Captain) message', () => {
    render(
      <ChatMessageRow
        msg={mkMsg({ id: 'm1', role: 'user', text: 'go' })}
        hostAgentId="a1"
        hostCallsign="Aria"
      />,
    );
    expect(screen.queryByTestId('agent-avatar-badge')).toBeNull();
    expect(screen.getByTestId('chat-msg-time').textContent).toMatch(/\d{1,2}:\d{2}/);
  });

  it('renders a system message with no avatar and the dim-italic bubble preserved', () => {
    const { container } = render(
      <ChatMessageRow
        msg={mkMsg({ id: 'm1', role: 'system', text: 'personality updated' })}
        hostAgentId="a1"
        hostCallsign="Aria"
      />,
    );
    expect(screen.queryByTestId('agent-avatar-badge')).toBeNull();
    expect(container.innerHTML).toContain('italic'); // existing system style preserved
  });

  it('formatChatTime formats a fixed epoch to an HH:MM shape (locale-agnostic)', () => {
    expect(formatChatTime(1_700_000_000)).toMatch(/\d{1,2}:\d{2}/);
    expect(formatChatTime(Number.NaN)).toBe('');
  });

  it('addAgentMessage is backward-compatible (no opts) and lands author info with opts', () => {
    useStore.setState({ agentConversations: new Map() });
    const { addAgentMessage } = useStore.getState();

    addAgentMessage('a1', 'agent', 'no-opts');
    let msgs = useStore.getState().agentConversations.get('a1')!.messages;
    expect(msgs).toHaveLength(1);
    expect(msgs[0].text).toBe('no-opts');
    expect(msgs[0].authorId).toBeUndefined();
    expect(msgs[0].callsign).toBeUndefined();

    addAgentMessage('a1', 'agent', 'with-opts', { authorId: 'a2', callsign: 'Lume' });
    msgs = useStore.getState().agentConversations.get('a1')!.messages;
    expect(msgs).toHaveLength(2);
    expect(msgs[1].authorId).toBe('a2');
    expect(msgs[1].callsign).toBe('Lume');
  });

  it('contains no emoji (HXI no-emoji guard) in source or rendered output', () => {
    expect(rowSource).not.toMatch(EMOJI_RE);
    seedAgents([mkAgent({ id: 'a1', callsign: 'Aria', department: 'science' })]);
    const { container } = render(
      <ChatMessageRow
        msg={mkMsg({ id: 'm1', role: 'agent', authorId: 'a1', callsign: 'Aria' })}
        hostAgentId="a1"
        hostCallsign="Aria"
      />,
    );
    expect(container.innerHTML).not.toMatch(EMOJI_RE);
  });
});
