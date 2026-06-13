/** AD-999: WorkspaceFolder — read-only view of an agent's code-execution
 *  working folder (AD-997/998), shown in the profile Work tab.
 *
 *  Bound to: GET /api/agent/{id}/workspace -> {enabled, persistent, root, path,
 *  owner, exists, files:[{name,is_dir,size_bytes,modified}], total_bytes}.
 *
 *  Honest states: execution off -> "disabled"; ephemeral -> "nothing persisted";
 *  enabled+persistent but no runs -> "No files yet"; otherwise the file list.
 *  HXI: stroke-only, amber active / dim inactive, NO emoji.
 */
import { useEffect, useState, useCallback } from 'react';

const _AMBER = '#f0b060';
const _DIM = '#666680';

export interface WorkspaceFile {
  name: string;
  is_dir: boolean;
  size_bytes: number;
  modified: number;
}

export interface WorkspaceInfo {
  enabled: boolean;
  persistent: boolean;
  root: string;
  path: string | null;
  owner: string | null;
  exists: boolean;
  files: WorkspaceFile[];
  total_bytes: number;
}

export async function fetchWorkspace(agentId: string): Promise<WorkspaceInfo> {
  const resp = await fetch(`/api/agent/${agentId}/workspace`);
  if (!resp.ok) throw new Error(`workspace fetch failed: ${resp.status}`);
  const d = await resp.json();
  return {
    enabled: !!d?.enabled,
    persistent: !!d?.persistent,
    root: d?.root ?? '',
    path: d?.path ?? null,
    owner: d?.owner ?? null,
    exists: !!d?.exists,
    files: Array.isArray(d?.files) ? d.files : [],
    total_bytes: typeof d?.total_bytes === 'number' ? d.total_bytes : 0,
  };
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

interface Deps {
  fetchWorkspace: (agentId: string) => Promise<WorkspaceInfo>;
}

interface Props {
  agentId: string;
  deps?: Deps;
}

const _hint = (text: string) => (
  <div style={{ color: '#444', fontSize: 10, padding: '4px 0' }}>{text}</div>
);

export function WorkspaceFolder({ agentId, deps }: Props) {
  const doFetch = deps?.fetchWorkspace ?? fetchWorkspace;
  const [info, setInfo] = useState<WorkspaceInfo | null>(null);
  const [error, setError] = useState(false);

  const load = useCallback(async () => {
    setError(false);
    try {
      setInfo(await doFetch(agentId));
    } catch {
      setError(true);
    }
  }, [agentId, doFetch]);

  useEffect(() => { void load(); }, [load]);

  const header = (
    <div style={{
      padding: '5px 0', fontSize: 11, fontWeight: 600, color: '#8888a0',
      display: 'flex', alignItems: 'center', gap: 6, marginTop: 8,
    }}>
      <span style={{ color: info?.enabled ? _AMBER : _DIM }}>{'\u27D0'}</span>
      Working folder
    </div>
  );

  return (
    <div data-testid="workspace-folder">
      {header}
      {error && _hint('Could not load working folder.')}
      {!error && info === null && <div data-testid="workspace-loading" style={{ color: '#444', fontSize: 10 }}>Loading…</div>}
      {!error && info !== null && (
        !info.enabled
          ? _hint('Code execution is disabled. Enable it in Settings \u2192 Code Execution.')
          : !info.persistent
            ? _hint('Ephemeral workspaces — nothing is persisted between runs.')
            : (
              <div style={{ fontSize: 11 }}>
                <div
                  data-testid="workspace-path"
                  title={info.path ?? ''}
                  style={{
                    fontFamily: 'monospace', fontSize: 10, color: '#8aa0c0',
                    wordBreak: 'break-all', marginBottom: 4,
                  }}
                >
                  {info.path}
                </div>
                {info.files.length === 0
                  ? _hint('No files yet — this agent has not run code.')
                  : (
                    <>
                      {info.files.map(f => (
                        <div
                          key={f.name}
                          data-testid={`workspace-file-${f.name}`}
                          style={{
                            display: 'flex', justifyContent: 'space-between', gap: 8,
                            padding: '2px 0', color: f.is_dir ? _AMBER : '#c8d0e0',
                          }}
                        >
                          <span style={{ fontFamily: 'monospace', wordBreak: 'break-all' }}>
                            {f.is_dir ? `${f.name}/` : f.name}
                          </span>
                          <span style={{ color: _DIM, flexShrink: 0 }}>
                            {f.is_dir && f.size_bytes === 0 ? '' : formatBytes(f.size_bytes)}
                          </span>
                        </div>
                      ))}
                      <div style={{ color: _DIM, fontSize: 10, marginTop: 4 }}>
                        {info.files.length} item{info.files.length === 1 ? '' : 's'} · {formatBytes(info.total_bytes)} total
                      </div>
                    </>
                  )}
              </div>
            )
      )}
    </div>
  );
}
