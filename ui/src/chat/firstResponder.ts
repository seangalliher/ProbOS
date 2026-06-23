// AD-962a: pick the LIKELY first responder for the AD-962 typing/thinking
// beat. Pure (no store/DOM/fetch) so it unit-tests in isolation and keeps the
// cosmetic guess off the hot path. The real fan-out reply still arrives
// correctly regardless of this guess.
import type { Agent } from '../store/types';

/** The callsign a message is DIRECTED TO at its start, or null. Mirrors the
 *  server crew_profile.extract_directed_callsign rule 1 (LEADING address only):
 *    "@yeo ..."  -> "yeo"   (chat-native @ form)
 *    "Yeo, ..."  -> "yeo"   (vocative comma)
 *    "Yeo: ..."  -> "yeo"   (vocative colon)
 *  A bare leading word with no @/,/: ("Data shows ...") is NOT an address. */
export function extractDirectedCallsign(text: string): string | null {
  if (!text) return null;
  const s = text.trimStart();
  const at = s.match(/^@(\w+)\b/);
  if (at) return at[1].toLowerCase();
  const vocative = s.match(/^(\w+)\s*[,:]/);
  if (vocative) return vocative[1].toLowerCase();
  return null;
}

/** AD-962a: the crew participant the Captain's message directly addresses, or
 *  null when no leading address resolves to a crew participant (caller then
 *  uses the AD-962 generic "The crew" beat). Excludes 'captain' and non-crew
 *  participants; case-insensitive callsign match (server returns lower-cased). */
export function resolveFirstResponder(
  text: string,
  participantIds: readonly string[],
  agents: ReadonlyMap<string, Agent>,
): { agentId: string; callsign: string } | null {
  const directed = extractDirectedCallsign(text);
  if (!directed) return null;
  for (const id of participantIds) {
    if (id === 'captain') continue;
    const a = agents.get(id);
    if (!a || !a.isCrew || !a.callsign) continue;
    if (a.callsign.toLowerCase() === directed) {
      return { agentId: id, callsign: a.callsign };
    }
  }
  return null;
}
