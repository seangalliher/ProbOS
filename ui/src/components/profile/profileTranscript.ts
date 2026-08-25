// AD-938: thread-keyed transcript helpers for the profile chat tab.
//
// Extracted from ProfileChatTab (the AD-936 ChatMessageRow precedent): the
// parent module pulls in heavy audio/screen deps that make it impractical to
// import under jsdom, so these pure/data-path helpers live here to stay
// independently testable. ProfileChatTab imports ``selectTranscriptMessages``
// (render source switch) and ``loadThreadMessages`` (the load-on-open effect).
import type { Agent, AgentProfileMessage } from '../../store/types';
import { listMessages, type ThreadMessageDTO } from '../sidebar/threadApi';

/** Map a persisted thread message (GET /messages DTO) into the profile
 *  transcript model. ``role`` collapses to the AD-936 three-state set: a
 *  ``captain`` author becomes a right-aligned ``'user'`` bubble (no avatar); an
 *  ``agent`` author keeps its per-message identity (``authorId`` + resolved
 *  ``callsign``) so ChatMessageRow shows the author avatar + name label;
 *  anything else renders as a centered ``'system'`` note. */
export function threadDtoToMessage(
  m: ThreadMessageDTO, agents: Map<string, Agent>,
): AgentProfileMessage {
  const isAgent = m.role === 'agent';
  // BF-766: the emotion used to ride only on the chat HTTP response, but the
  // server appends and pushes the row BEFORE returning that body, so the
  // transcript usually wins the shared speech claim and spoke flat.
  const rawEmotion = m.metadata?.emotion;
  return {
    id: m.id,
    role: m.role === 'captain' ? 'user' : (isAgent ? 'agent' : 'system'),
    text: m.body,
    timestamp: m.created_at,
    authorId: isAgent ? m.author_id : undefined,
    callsign: isAgent ? (agents.get(m.author_id)?.callsign ?? undefined) : undefined,
    emotion: typeof rawEmotion === 'string' && rawEmotion.length > 0
      ? rawEmotion
      : undefined,
  };
}

/** Choose the displayed transcript. With an active thread (group or warm 1:1)
 *  render that thread's real messages; with no thread (a cold 1:1 before its
 *  first send) fall back to the per-agent ``agentConversations`` buffer so the
 *  AD-406 first-send UX is unchanged. */
export function selectTranscriptMessages(
  activeThreadId: string | null | undefined,
  threadMsgs: AgentProfileMessage[] | undefined,
  conversationMsgs: AgentProfileMessage[] | undefined,
): AgentProfileMessage[] {
  return activeThreadId ? (threadMsgs ?? []) : (conversationMsgs ?? []);
}

// AD-1056: chat transcript day-separators + render cap. Messages carry
// ``timestamp`` as UNIX seconds (server ``time.time()``; same convention as
// threadGrouping.ts). The transcript inserts a calendar-day separator before the
// first message of each new LOCAL day, and renders at most
// ``TRANSCRIPT_RENDER_CAP`` of the most recent messages so opening a long
// history is a bounded view, not a disorienting wall of text streamed from the
// top.

export const TRANSCRIPT_RENDER_CAP = 200;

export type TranscriptItem =
  | { kind: 'day'; id: string; label: string }
  | { kind: 'msg'; id: string; msg: AgentProfileMessage };

/** Local calendar-day key (YYYY-M-D) for a UNIX-seconds timestamp. Returns ''
 *  for a missing/invalid timestamp so such messages never force a separator. */
function dayKeyOfSeconds(timestampSec: number): string {
  if (!timestampSec || !Number.isFinite(timestampSec)) return '';
  const d = new Date(timestampSec * 1000);
  if (Number.isNaN(d.getTime())) return '';
  return `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`;
}

/** Human label for a day separator: Today / Yesterday / a locale date. ``nowMs``
 *  is injected so tests can pin a fixed reference instant. */
export function transcriptDayLabel(timestampSec: number, nowMs: number): string {
  const dayMs = 86_400_000;
  const startOfToday = new Date(nowMs).setHours(0, 0, 0, 0);
  const startOfYesterday = startOfToday - dayMs;
  const ms = timestampSec * 1000;
  if (ms >= startOfToday) return 'Today';
  if (ms >= startOfYesterday) return 'Yesterday';
  return new Date(ms).toLocaleDateString(undefined, {
    weekday: 'short', month: 'short', day: 'numeric', year: 'numeric',
  });
}

/** Build the renderable transcript: cap to the most recent ``cap`` messages,
 *  then insert a day separator before the first message of each local day. A
 *  ``cap`` of 0 disables the cap. Pure — no DOM/store deps, so it is exercised
 *  by a focused vitest. */
export function buildTranscriptItems(
  messages: AgentProfileMessage[],
  opts: { nowMs?: number; cap?: number } = {},
): TranscriptItem[] {
  const cap = opts.cap ?? TRANSCRIPT_RENDER_CAP;
  const nowMs = opts.nowMs ?? Date.now();
  const capped = cap > 0 && messages.length > cap
    ? messages.slice(messages.length - cap)
    : messages;
  const items: TranscriptItem[] = [];
  let lastDayKey = '';
  for (const msg of capped) {
    const dayKey = dayKeyOfSeconds(msg.timestamp);
    if (dayKey && dayKey !== lastDayKey) {
      lastDayKey = dayKey;
      items.push({ kind: 'day', id: `day-${dayKey}`, label: transcriptDayLabel(msg.timestamp, nowMs) });
    }
    items.push({ kind: 'msg', id: msg.id, msg });
  }
  return items;
}

/** Load a thread's persisted transcript and publish it to the store.
 *  ``listMessages`` already Tier-2 degrades to ``[]``; the setter is injected so
 *  the caller can guard against a stale/unmounted write. */
export async function loadThreadMessages(
  threadId: string,
  agents: Map<string, Agent>,
  setThreadMessages: (threadId: string, msgs: AgentProfileMessage[]) => void,
): Promise<void> {
  const dtos = await listMessages(threadId);
  setThreadMessages(threadId, dtos.map((m) => threadDtoToMessage(m, agents)));
}

// ── BF-718: every speaker claims before it speaks ──────────────────────────
//
// Speech used to be bound to the request/response path, so a reply the UI asked
// for was spoken and a message the server pushed was not. A promoted turn's
// report (AD-1165) is appended server-side and arrives as
// CHAT_THREAD_MESSAGE_APPENDED — it reached the transcript and never reached
// the speaker.
//
// The first attempt at this added a transcript watcher ALONGSIDE the existing
// speakers and was reverted: ProfileChatTab already had three (the send round
// trip, the AD-1062 call greeting, and the BF-290 conversation-mode callback),
// so a fourth produced duplicates, and no id-based marking wins the race
// between an HTTP response and the WebSocket event the server emits before
// returning it.
//
// So the four speakers share a CLAIM instead. Each asks the ledger for the
// right to speak a given piece of content before speaking it, and exactly one
// gets it. Keying on content rather than on message id is what makes that work
// in both directions: the send path's optimistic row and the server's canonical
// row carry different ids but identical text, so whichever lands first claims
// it and the other falls silent. Neither has to know it raced.
//
// The transcript effect is the speaker that closes BF-718 — it is the only one
// that sees messages nobody requested. The other three are kept because each
// sees something it cannot: a reply landing in a thread the Captain has already
// navigated away from (BF-671), and the conversation-mode turn-taking signal
// that has to fire from whoever actually spoke (BF-290).

/** BF-765: the ledger shape and its app-lifetime singleton live in an
 *  importless module so the global vitest setup can reset it safely.
 *  Re-exported here because this is where every caller already looks. */
import type { SpeechLedger, SpeechScope } from './speechLedgerStore';

export type { SpeechLedger, SpeechScope } from './speechLedgerStore';
export {
  createSpeechLedger,
  resetSharedSpeechLedger,
  sharedSpeechLedger,
} from './speechLedgerStore';

/** Bound per scope. Insertion-ordered, oldest evicted first. */
export const SPEECH_SCOPE_CAP = 500;

/** BF-768: bound on the number of SCOPES, not just keys within one.
 *
 *  Nothing capped this while the ledger lived on a component ref, because a
 *  remount discarded the whole thing. BF-765 makes it outlive the mount, which
 *  turns an unbounded map into a real leak: one entry per thread or per-agent
 *  buffer ever visited, for the life of the tab. Evicted least-recently-used,
 *  so the scopes the Captain is actually moving between survive.
 *
 *  Sized above the sidebar's 100-thread hydration so a Captain moving among
 *  loaded threads does not cross it in ordinary use. Past the bound an evicted
 *  scope forgets and its content may be spoken again -- the accepted cost, and
 *  the reason the cap is not smaller. */
export const SPEECH_LEDGER_SCOPE_CAP = 128;

/** Has this scope's existing history been seeded yet? Marks it as seeded. */
export function markScopeSeen(ledger: SpeechLedger, scopeKey: string): boolean {
  const scope = scopeRecord(ledger, scopeKey);
  const first = !scope.seen;
  scope.seen = true;
  return first;
}

/** Identity for speech: role + author + trimmed text, NOT the message id.
 *
 *  ``sendText`` appends its reply locally with a generated id and the server's
 *  own append then replaces it with the canonical row under a different id.
 *  Sharing one claim across both, a content key collapses them; an id key would
 *  speak every ordinary reply twice. Two identical messages from one author
 *  also collapse, so the second is silent — the safe direction, since the
 *  alternative is talking over the Captain.
 *
 *  ``defaultAuthorId`` matters more than it looks: ``addAgentMessage`` omits
 *  ``authorId`` entirely on the 1:1 buffer (AD-936 only sets it for group
 *  replies), so a claim made with an explicit agent id would not match the row
 *  it was made for, and both speakers would fire. In a 1:1 an agent message
 *  with no author IS from the mounted agent — the same assumption the speaking
 *  effect already makes when it picks a voice.
 *
 *  ``role`` leads the key because that default is applied to EVERY row,
 *  including the Captain's. Without it, the Captain typing "Echo me" claims the
 *  agent's identical reply and the reply is silent. Role alone is enough — the
 *  author default may be applied to a non-agent row without harm once the roles
 *  cannot collide, so there is deliberately no second guard here to drift out
 *  of step with this one. */
export function speechKeyFor(
  msg: Pick<AgentProfileMessage, 'authorId' | 'text' | 'role'>,
  defaultAuthorId = '',
): string {
  return `${msg.role ?? ''}\u0000${msg.authorId || defaultAuthorId}\u0000${(msg.text ?? '').trim()}`;
}

/** Whether a message is the kind of thing that gets spoken at all.
 *
 *  The parenthetical rule is inherited, not invented: the send path has always
 *  skipped ``(no response)`` / ``(communication error)`` / ``(error: …)``, and
 *  moving the decision here has to bring that with it or the Captain starts
 *  hearing placeholders read aloud. */
export function isSpeakableAgentMessage(msg: AgentProfileMessage): boolean {
  if (msg.role !== 'agent') return false;
  const text = (msg.text ?? '').trim();
  return text.length > 0 && !text.startsWith('(');
}

/** The scope's record, touched for LRU and evicting past the bound.
 *
 *  Every reader goes through here, so claims and the seeded flag are always
 *  evicted as one unit. */
function scopeRecord(ledger: SpeechLedger, scopeKey: string): SpeechScope {
  let scope = ledger.scopes.get(scopeKey);
  if (!scope) {
    scope = { keys: new Set<string>(), seen: false };
  } else {
    // Re-insert so Map insertion order is recency order, making the eviction
    // below least-recently-USED rather than least-recently-created.
    ledger.scopes.delete(scopeKey);
  }
  ledger.scopes.set(scopeKey, scope);
  while (ledger.scopes.size > SPEECH_LEDGER_SCOPE_CAP) {
    const oldest = ledger.scopes.keys().next();
    if (oldest.done) break;
    ledger.scopes.delete(oldest.value);
  }
  return scope;
}

function remember(set: Set<string>, key: string): void {
  set.add(key);
  while (set.size > SPEECH_SCOPE_CAP) {
    const oldest = set.values().next();
    if (oldest.done) break;
    set.delete(oldest.value);
  }
}

/** Take the right to speak ``msg`` in ``scopeKey``, once.
 *
 *  Returns true only for the caller that got there first AND only when the
 *  content is the kind of thing that gets spoken at all. Every later caller
 *  gets false, so the losers of the HTTP-versus-WebSocket race stay silent
 *  without needing to know they lost. Recording happens either way — an
 *  unspeakable message still consumes its key, so a placeholder cannot be
 *  "claimed" a second time by a different speaker.
 *
 *  This is synchronous and same-tick: both speakers run on one event loop in
 *  one component, so there is no window between the check and the claim. */
export function claimSpeech(
  ledger: SpeechLedger,
  scopeKey: string,
  msg: AgentProfileMessage,
  defaultAuthorId = '',
): boolean {
  const set = scopeRecord(ledger, scopeKey).keys;
  const key = speechKeyFor(msg, defaultAuthorId);
  if (set.has(key)) return false;
  remember(set, key);
  return isSpeakableAgentMessage(msg);
}

/** The scope a claim belongs to. A thread when there is one, otherwise the
 *  per-agent buffer — the two speakers must agree on this or they would claim
 *  in different scopes and both speak. */
export function speechScopeKey(threadId: string | null | undefined, agentId: string): string {
  return threadId ? threadId : `agent:${agentId}`;
}

/** Record every message in ``messages`` against ``scopeKey`` and return the
 *  ones that are newly arrived AND speakable.
 *
 *  ``seed: true`` records without returning anything. The caller passes it
 *  until the scope's transcript has actually loaded, and again after a
 *  reconnect repair — both are moments when the whole history shows up at once
 *  and none of it is a live arrival. Inferring that from how MANY messages
 *  appeared does not work: the first render of a thread has an empty list
 *  because the transcript hydrates asynchronously, so the real history arrives
 *  afterwards and looks exactly like new traffic.
 *
 *  ``liveIds`` is the exception that keeps seeding from swallowing a real
 *  arrival. A push can land WHILE a seeding load is in flight, and that load's
 *  response can already contain the pushed row — blanket-seeding the array then
 *  claims it silently and the follow-up refresh finds nothing left to say,
 *  which is BF-718 all over again. Messages whose id is listed here are known
 *  to be live and are admitted even while seeding. */
export function admitMessages(
  ledger: SpeechLedger,
  scopeKey: string,
  messages: readonly AgentProfileMessage[],
  opts: { seed: boolean; defaultAuthorId?: string; liveIds?: ReadonlySet<string> },
): AgentProfileMessage[] {
  const admitted: AgentProfileMessage[] = [];
  for (const msg of messages) {
    const isLive = !opts.seed || !!opts.liveIds?.has(msg.id);
    if (claimSpeech(ledger, scopeKey, msg, opts.defaultAuthorId) && isLive) {
      admitted.push(msg);
    }
  }
  return admitted;
}
