/*
 * AD-793 (Wave 196) — Thin fetch wrappers for the projects REST surface.
 *
 * Mirrors threadApi.ts. Response-shape contracts verified against
 * ``src/probos/routers/projects.py``:
 *   - GET    /api/projects                  -> {projects: ProjectView[]}
 *   - POST   /api/projects                  -> ProjectView (direct, no wrapper)
 *   - GET    /api/projects/{id}             -> ProjectView (direct)
 *   - PATCH  /api/projects/{id}             -> ProjectView (direct)
 *   - DELETE /api/projects/{id}             -> {deleted, affected_threads, cascade}
 *   - POST   /api/projects/{id}/pin         -> ProjectView (direct)
 *   - POST   /api/projects/{id}/unpin       -> ProjectView (direct)
 *
 * All wrappers honest-degrade on network failure (return ``null`` /
 * empty array) so the sidebar can keep rendering its current state.
 */
import type { ProjectView } from '../../store/useStore';

export interface ListProjectsOptions {
  includeArchived?: boolean;
  limit?: number;
}

export async function listProjects(opts: ListProjectsOptions = {}): Promise<ProjectView[]> {
  const includeArchived = opts.includeArchived ?? false;
  const limit = opts.limit ?? 100;
  try {
    const res = await fetch(`/api/projects?include_archived=${includeArchived}&limit=${limit}`);
    if (!res.ok) return [];
    const data = (await res.json()) as { projects?: ProjectView[] };
    return Array.isArray(data?.projects) ? data.projects : [];
  } catch {
    return [];
  }
}

export interface CreateProjectBody {
  name: string;
  description?: string;
  pinned_attachment_ids?: string[];
}

export async function createProject(body: CreateProjectBody): Promise<ProjectView | null> {
  try {
    const res = await fetch('/api/projects', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) return null;
    const data = (await res.json()) as ProjectView;
    return data && typeof data.id === 'string' ? data : null;
  } catch {
    return null;
  }
}

export interface PatchProjectBody {
  name?: string;
  description?: string;
  archived?: boolean;
}

export async function patchProject(
  projectId: string,
  body: PatchProjectBody,
): Promise<ProjectView | null> {
  try {
    const res = await fetch(`/api/projects/${encodeURIComponent(projectId)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) return null;
    const data = (await res.json()) as ProjectView;
    return data && typeof data.id === 'string' ? data : null;
  } catch {
    return null;
  }
}

export interface DeleteProjectResponse {
  deleted: boolean;
  affected_threads: number;
  cascade: boolean;
}

export async function deleteProject(
  projectId: string,
  options: { cascade?: boolean } = {},
): Promise<DeleteProjectResponse | null> {
  const cascade = options.cascade ?? false;
  try {
    const res = await fetch(
      `/api/projects/${encodeURIComponent(projectId)}?cascade=${cascade}`,
      { method: 'DELETE' },
    );
    if (!res.ok) return null;
    const data = (await res.json()) as DeleteProjectResponse;
    return data;
  } catch {
    return null;
  }
}
