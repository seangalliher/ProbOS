/** BF-812: recognise an AD-698 pre-intent policy refusal.
 *
 *  The backend answers a denied intent with `403 {"error":"intent_denied",
 *  "reason":"rbac"}`. Every chat surface has to tell that apart from a
 *  transport failure, because the two demand opposite handling:
 *
 *  - a transport failure may be retried or routed around;
 *  - a policy refusal must NOT be, and re-sending it through a different
 *    endpoint completes by another route the exact action policy just
 *    refused. A policy is evaluated PER INTENT, so a hook refusing
 *    `direct_message` may well permit `ward_room_notification`.
 *
 *  Keyed on the body rather than the status so that a future status change
 *  cannot silently re-open that bypass. The status is corroborating, not
 *  required — callers additionally refuse to reroute ANY 4xx, whatever body
 *  shape it carries.
 *
 *  PRODUCER: `src/probos/api.py` `_denied`, which answers
 *  `{"error": "intent_denied", "intent": ..., "reason": ...}`. That body is
 *  pinned by `tests/test_bf771_intent_authorization.py`, which names this
 *  module in turn. No single test spans the two languages, so both sides pin
 *  the contract and a change to either breaks a test.
 */

export interface PolicyDenial {
  readonly reason: string;
}

/** The denial carried by a response body, or null if this is not one. */
export function policyDenialOf(body: unknown): PolicyDenial | null {
  if (typeof body !== 'object' || body === null) return null;
  const record = body as Record<string, unknown>;
  if (record.error !== 'intent_denied') return null;
  const reason = typeof record.reason === 'string' && record.reason.length > 0
    ? record.reason
    : 'policy';
  return { reason };
}

/** Captain-facing text for a refusal.
 *
 *  Deliberately not phrased as an agent turn and not as an outage. Rendering
 *  it as `"(no response)"` told the Captain the agent had nothing to say,
 *  which is a refusal wearing an outage costume.
 */
export function denialNotice(denial: PolicyDenial): string {
  return `Policy refused this request (${denial.reason}). Nothing was sent.`;
}
