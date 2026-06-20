// AD-1023: backing-store binding — reads the AD-997 execution work folder via the
// AD-998 read endpoint. Layer discipline: the Experience layer reaches the folder
// through the runtime API only, never importing execution.workspace.
import type { WorkspaceFolder } from '../../store/types';

export async function fetchWorkspaceFolder(agentId: string): Promise<WorkspaceFolder> {
  const r = await fetch(`/api/agent/${encodeURIComponent(agentId)}/workspace`);
  if (!r.ok) throw new Error(`workspace folder fetch failed: ${r.status}`);
  return (await r.json()) as WorkspaceFolder;
}
