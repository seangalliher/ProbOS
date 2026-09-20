import type { AgentProfileMessage, CapabilityApprovalView } from '../../store/types';
import { useStore, isCapabilityRequestView } from '../../store/useStore';
import { CapabilityRequestCard } from '../capability/CapabilityRequestCard';

const NO_WORK = 'I have stopped and need your approval to keep going \u2014 this turn reached its step limit before I had anything to report back. The task is still open.';
const WITH_WORK = 'I have stopped and need your approval to keep going \u2014 this turn reached its step limit with the task still open. Partial work is below.';
const TAIL = ' Approve the pending request in the Bridge and I will pick up from exactly where this stopped. (Request ';
const UUID_END = /^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.\)/;

export function parseContinueApprovalNotice(text: string): string | null {
  if (typeof text !== 'string') return null;
  const withWork = text.startsWith(WITH_WORK + TAIL);
  const prefix = withWork ? WITH_WORK + TAIL : NO_WORK + TAIL;
  if (!text.startsWith(prefix)) return null;
  const rest = text.slice(prefix.length);
  const match = UUID_END.exec(rest);
  if (!match) return null;
  const suffix = rest.slice(match[0].length);
  if (withWork ? !suffix.startsWith('\n\n---\n') || suffix.length <= 6 : suffix !== '') return null;
  return match[1];
}

function matchesMessage(request: CapabilityApprovalView, msg: AgentProfileMessage, activeThreadId: string): boolean {
  return request.agent_id === msg.authorId && request.kind === 'continue'
    && request.payload?.tool_id === 'dm_agentic' && request.payload.action === 'continue'
    && request.payload.scope_key === '' && request.payload.thread_id === msg.threadId
    && request.payload.thread_id === activeThreadId;
}

/** Provenance gates controls; host/visual author fallbacks are never consulted. */
export function InlineCapabilityApproval({ msg, activeThreadId }: {
  msg: AgentProfileMessage; activeThreadId?: string;
}): React.JSX.Element | null {
  const resource = useStore(state => state.approvalResources.capability);
  const feedback = useStore(state => state.capabilityDecisionFeedback);
  const id = parseContinueApprovalNotice(msg.text);
  if (!id || msg.role !== 'agent' || typeof msg.authorId !== 'string' || !msg.authorId.trim()
    || typeof msg.threadId !== 'string' || !msg.threadId.trim()
    || msg.threadId !== activeThreadId || !activeThreadId) return null;
  const request = resource.data?.requests.filter(isCapabilityRequestView).find(row => row.id === id);
  if (request && !matchesMessage(request, msg, activeThreadId)) return null;
  const confirmed = feedback.get(id);
  if (!request && confirmed && !matchesMessage(confirmed.outcome.request, msg, activeThreadId)) return null;
  return <CapabilityRequestCard requestId={id} request={request} inline />;
}
