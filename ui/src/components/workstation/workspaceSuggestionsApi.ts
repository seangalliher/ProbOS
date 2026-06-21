/**
 * AD-1021c: same-origin fetch wrappers for the Monaco co-edit surface — listing,
 * proposing, and dismissing per-file agent suggestions against an agent's AD-997
 * workspace folder.
 *
 * Endpoints (mounted under /api/agent/{id}):
 *   GET  /workspace/suggestions?path=<rel>          list pending suggestions (honest-degrade [])
 *   POST /workspace/suggestions                     propose a full-content change
 *   POST /workspace/suggestions/{sid}/dismiss       decline a suggestion -> {dismissed}
 *
 * Accept is NOT here — it reuses the AD-1021b governed write `saveWorkspaceFile`
 * (POST /workspace/file, consensus-gated). DD-1: same-origin, NO token in browser
 * JS. The whole surface honest-degrades: a list failure -> `[]`, a 503 (co-edit
 * master switch OFF) -> a benign empty/false rather than a thrown error, so the
 * HXI shows calm state instead of crashing.
 */

export interface WorkspaceSuggestion {
  id: string;
  owner: string;
  path: string;
  content: string;
  author_id: string;
  author_callsign: string;
  note: string;
  created_at: number;
}

export interface WorkspaceSuggestionCreate {
  path: string;
  content: string;
  author_id: string;
  author_callsign?: string;
  note?: string;
}

export async function listWorkspaceSuggestions(
  agentId: string,
  path: string,
): Promise<WorkspaceSuggestion[]> {
  try {
    const res = await fetch(
      `/api/agent/${encodeURIComponent(agentId)}/workspace/suggestions?path=${encodeURIComponent(path)}`,
    );
    if (!res.ok) return [];
    const data = (await res.json()) as { suggestions?: WorkspaceSuggestion[] };
    return data.suggestions ?? [];
  } catch {
    // Network/parse failure -> honest-degrade to no suggestions (never throw).
    return [];
  }
}

export async function postWorkspaceSuggestion(
  agentId: string,
  body: WorkspaceSuggestionCreate,
): Promise<WorkspaceSuggestion | null> {
  const res = await fetch(
    `/api/agent/${encodeURIComponent(agentId)}/workspace/suggestions`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
  );
  // Co-edit master switch OFF -> honest-degrade to null (caller shows a banner).
  if (res.status === 503) return null;
  if (!res.ok) {
    throw new Error(`postWorkspaceSuggestion: ${res.status}`);
  }
  const data = (await res.json()) as { suggestion?: WorkspaceSuggestion };
  return data.suggestion ?? null;
}

export async function dismissWorkspaceSuggestion(
  agentId: string,
  suggestionId: string,
): Promise<boolean> {
  try {
    const res = await fetch(
      `/api/agent/${encodeURIComponent(agentId)}/workspace/suggestions/${encodeURIComponent(suggestionId)}/dismiss`,
      { method: 'POST' },
    );
    if (!res.ok) return false;
    const data = (await res.json()) as { dismissed?: boolean };
    return Boolean(data.dismissed);
  } catch {
    return false;
  }
}
