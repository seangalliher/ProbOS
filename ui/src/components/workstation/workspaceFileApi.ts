/**
 * AD-1021b: same-origin fetch wrappers for the Monaco workstation write-through
 * to an agent's AD-997 workspace folder.
 *
 * Endpoints (mounted under /api/agent/{id}):
 *   GET  /workspace/file?path=<rel>   read one confined file (honest-degrade found:false)
 *   POST /workspace/file              governed write (consensus); 503 when default-OFF
 *
 * DD-1: same-origin, NO token in browser JS — the HXI calls the API on the same
 * origin (pass-through while auth.crew_scope_token==""). The read honest-degrades
 * to `found:false`; the save honest-degrades a 503 (write master switch OFF) to
 * `{ outcome: 'disabled' }` so the UI shows a banner rather than throwing.
 */

export interface WorkspaceFileLoad {
  found: boolean;
  content: string | null;
  size_bytes?: number;
  too_large?: boolean;
}

export interface WorkspaceSaveResult {
  outcome: 'committed' | 'refused' | 'disabled';
  consensus_outcome?: string;
  approval_ratio?: number;
  path?: string;
}

export async function loadWorkspaceFile(
  agentId: string,
  path: string,
): Promise<WorkspaceFileLoad> {
  const res = await fetch(
    `/api/agent/${encodeURIComponent(agentId)}/workspace/file?path=${encodeURIComponent(path)}`,
  );
  if (!res.ok) {
    throw new Error(`loadWorkspaceFile: ${res.status}`);
  }
  return (await res.json()) as WorkspaceFileLoad;
}

export async function saveWorkspaceFile(
  agentId: string,
  path: string,
  content: string,
): Promise<WorkspaceSaveResult> {
  const res = await fetch(
    `/api/agent/${encodeURIComponent(agentId)}/workspace/file`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path, content }),
    },
  );
  // Default-OFF master switch -> honest-degrade to a "disabled" banner, not an error.
  if (res.status === 503) {
    return { outcome: 'disabled' };
  }
  if (!res.ok) {
    throw new Error(`saveWorkspaceFile: ${res.status}`);
  }
  return (await res.json()) as WorkspaceSaveResult;
}
