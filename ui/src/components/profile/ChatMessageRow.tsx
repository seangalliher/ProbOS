// AD-936: per-message metadata row for the profile chat transcript —
// Teams/Slack/Discord-style author avatar + name label + HH:MM timestamp.
//
// Extracted as a small presentational component because the ProfileChatTab
// bubble JSX is heavy and the parent module pulls in audio/screen deps that
// make a full-component render impractical under jsdom (the groupsend/bf294b
// precedent). This row imports only useStore + AgentAvatarBadge, so it is
// independently renderable and testable.
//
// Pure render: author identity comes from the message model (AD-936
// authorId/callsign threaded by the group fan-out); the avatar color
// (department) is a defensive runtime cast on the base Agent — the
// ChatsPanel/IntentSurface precedent — since `department` is not a declared
// field on Agent. The message body is passed in pre-rendered so this row
// stays decoupled from the AD-797 artifact-stub renderer.
import type { ReactNode } from 'react';
import { useStore } from '../../store/useStore';
import type { Agent, AgentProfileMessage } from '../../store/types';
import { AgentAvatarBadge } from '../AgentAvatarBadge';

// `department` is a runtime cast on the base Agent (ChatsPanel precedent),
// not a declared field — read it defensively for the avatar color.
function deptOf(agent: Agent | undefined): string {
  return (agent as (Agent & { department?: string }) | undefined)?.department ?? '';
}

/** Pure: format an epoch-seconds timestamp to a locale-local HH:MM. */
export function formatChatTime(tsSeconds: number): string {
  if (!Number.isFinite(tsSeconds)) return '';
  return new Date(tsSeconds * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

interface Props {
  msg: AgentProfileMessage;
  hostAgentId: string;
  hostCallsign: string;
  // Pre-rendered message body (artifact stubs resolved by the parent). When
  // omitted the raw text is shown — keeps the row usable/testable standalone.
  body?: ReactNode;
}

export function ChatMessageRow({ msg, hostAgentId, hostCallsign, body }: Props) {
  const agents = useStore((s) => s.agents);
  const isAgent = msg.role === 'agent';
  const isUser = msg.role === 'user';
  const isSystem = msg.role === 'system';
  // AD-936: per-message author falls back to the host agent for 1:1 / legacy
  // messages that predate the authorId/callsign fields.
  const authorId = msg.authorId ?? hostAgentId;
  const authorAgent = agents.get(authorId);
  // BF-614: a group fan-out reply can arrive with a BLANK callsign (the
  // backend couldn't resolve it for an added participant) - and `?? hostCallsign`
  // does NOT catch '' (only null/undefined), so the badge fell to the empty
  // initial '?'. Resolve from the agents map by the real authorId first; only a
  // legacy/1:1 message with NO explicit author falls back to the host callsign
  // (a group reply whose author we genuinely can't resolve keeps '' -> the
  // honest '?' badge, never a wrong host attribution).
  const authorCallsign =
    (msg.callsign && msg.callsign.trim())
    || authorAgent?.callsign
    || (msg.authorId != null ? '' : hostCallsign);
  const dept = deptOf(authorAgent);
  const time = formatChatTime(msg.timestamp);

  const dimColor = '#666680';
  const header = isAgent ? (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 3 }}>
      <AgentAvatarBadge agentId={authorId} callsign={authorCallsign} department={dept} size={24} />
      <span style={{ fontSize: 11, fontWeight: 600, color: '#9a9a9a' }}>{authorCallsign}</span>
      {time && (
        <span data-testid="chat-msg-time" style={{ fontSize: 10, color: dimColor }}>{time}</span>
      )}
    </div>
  ) : (
    time ? (
      <div style={{ marginBottom: 2 }}>
        <span data-testid="chat-msg-time" style={{ fontSize: 10, color: dimColor }}>{time}</span>
      </div>
    ) : null
  );

  return (
    <div
      style={{
        marginBottom: 8,
        textAlign: isUser ? 'right' : (isSystem ? 'center' : 'left'),
      }}
    >
      {header}
      <div style={{
        display: 'inline-block',
        maxWidth: '85%',
        padding: '6px 10px',
        borderRadius: 8,
        fontSize: 12,
        lineHeight: 1.5,
        background: isUser
          ? 'rgba(240, 176, 96, 0.15)'
          : (isSystem
            ? 'rgba(255, 255, 255, 0.02)'
            : 'rgba(255, 255, 255, 0.05)'),
        border: isUser
          ? '1px solid rgba(240, 176, 96, 0.2)'
          : (isSystem
            ? '1px dashed rgba(255, 255, 255, 0.12)'
            : '1px solid rgba(255, 255, 255, 0.06)'),
        color: isSystem ? '#9a9a9a' : '#e0dcd4',
        fontStyle: isSystem ? 'italic' : 'normal',
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-word',
      }}>
        {body ?? msg.text}
      </div>
    </div>
  );
}
