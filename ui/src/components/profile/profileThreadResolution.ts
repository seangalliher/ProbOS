/**
 * AD-937: shared 3-way resolver for the thread a profile chat addresses.
 *
 * Precedence: explicit ``props.threadId`` (AD-792) > the AD-937 group override
 * (``activeProfileThreadId``) > the agent's per-agent 1:1 default
 * (``threadIdByAgent``). The override lets a group be addressed WITHOUT
 * clobbering the agent's single 1:1 slot, so a roster open (which clears the
 * override via ``openAgentProfile``) re-resolves to the 1:1 — the fix for the
 * unreachable-1:1 regression. Extracted as a pure function so the resolution
 * priority is unit-testable without rendering the audio-dep-laden ProfileChatTab.
 */
export function resolveProfileThreadId(
  propThreadId: string | undefined,
  activeProfileThreadId: string | null,
  threadIdByAgent: Map<string, string>,
  agentId: string,
): string | undefined {
  return propThreadId ?? activeProfileThreadId ?? threadIdByAgent.get(agentId);
}
