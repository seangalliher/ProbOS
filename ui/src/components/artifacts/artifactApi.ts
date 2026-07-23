/**
 * AD-797 (Wave 197): fetch wrappers for the artifacts pane.
 *
 * Endpoints (mounted at /api/artifacts):
 *   GET    /thread/{thread_id}            list native + project-pinned
 *   GET    /{artifact_id}                 metadata
 *   GET    /{artifact_id}/content         raw bytes (any mime)
 *   POST   /api/projects/{id}/pin         pin a content_hash to a project
 *
 * All helpers honest-degrade — non-ok responses surface via thrown
 * Error so the caller's try/catch can show a toast without crashing
 * the drawer.
 */
import type { ArtifactView } from '../../store/useStore';

function isArtifactMetadata(value: unknown): value is Omit<ArtifactView, '_pinned_from_project'> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  const row = value as Record<string, unknown>;
  return typeof row.id === 'string'
    && typeof row.thread_id === 'string'
    && typeof row.name === 'string'
    && Number.isInteger(row.version)
    && typeof row.content_hash === 'string'
    && typeof row.mime === 'string'
    && Number.isInteger(row.size_bytes)
    && typeof row.created_by === 'string'
    && typeof row.created_at === 'number'
    && (row.supersedes === null || typeof row.supersedes === 'string');
}

export async function fetchArtifactMetadata(
  artifactId: string,
): Promise<ArtifactView | null> {
  try {
    const res = await fetch(`/api/artifacts/${encodeURIComponent(artifactId)}`);
    if (!res.ok) return null;
    const data: unknown = await res.json();
    if (!isArtifactMetadata(data)) return null;
    return { ...data, _pinned_from_project: false };
  } catch {
    return null;
  }
}

export async function fetchThreadArtifacts(
  threadId: string,
): Promise<ArtifactView[]> {
  const res = await fetch(`/api/artifacts/thread/${encodeURIComponent(threadId)}`);
  if (!res.ok) {
    throw new Error(`fetchThreadArtifacts: ${res.status}`);
  }
  const body = await res.json();
  return Array.isArray(body.artifacts) ? body.artifacts : [];
}

export async function fetchArtifactContent(
  artifactId: string,
): Promise<{ blob: Blob; text: string; mime: string }> {
  const res = await fetch(
    `/api/artifacts/${encodeURIComponent(artifactId)}/content`,
  );
  if (!res.ok) {
    throw new Error(`fetchArtifactContent: ${res.status}`);
  }
  const mime = res.headers.get('content-type') ?? 'application/octet-stream';
  const blob = await res.blob();
  // For binary mimes (images, uri-list), the caller decides whether
  // to use blob or text; we compute text once for the cheap case.
  let text = '';
  if (
    mime.startsWith('text/') ||
    mime === 'application/json' ||
    mime === 'application/yaml' ||
    mime === 'application/sql'
  ) {
    text = await blob.text();
  }
  return { blob, text, mime };
}

export async function pinArtifactToProject(
  projectId: string, contentHash: string,
): Promise<void> {
  const res = await fetch(`/api/projects/${encodeURIComponent(projectId)}/pin`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ attachment_id: contentHash }),
  });
  if (!res.ok) {
    throw new Error(`pinArtifactToProject: ${res.status}`);
  }
}

/**
 * AD-797: stub line format produced by the Python extractor.
 * Exposed here so ArtifactCard + drawer share one regex.
 *
 * Matches:  [Artifact: <name> v<version> - <lines> lines, <mime>]
 * ASCII hyphen (NOT em-dash).
 */
export const ARTIFACT_STUB_RE =
  /^\[Artifact: ([^\]]+?) v(\d+) - (\d+) lines, ([^\]]+)\]$/;

export interface ParsedStub {
  name: string;
  version: number;
  lineCount: number;
  mime: string;
}

export function parseArtifactStub(line: string): ParsedStub | null {
  const m = ARTIFACT_STUB_RE.exec(line);
  if (!m) return null;
  return {
    name: m[1],
    version: parseInt(m[2], 10),
    lineCount: parseInt(m[3], 10),
    mime: m[4],
  };
}
