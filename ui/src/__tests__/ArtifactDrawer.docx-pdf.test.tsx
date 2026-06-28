/** AD-1074b: docx (mammoth -> sanitized HTML) + pdf (native iframe) render in
 *  the ArtifactViewer. Mirrors the AD-797 ArtifactDrawer test setup. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor, cleanup } from '@testing-library/react';
import { useStore, type ArtifactView } from '../store/useStore';
import { ArtifactDrawer } from '../components/artifacts/ArtifactDrawer';

// The viewer dynamic-imports the mammoth browser build; mock it.
vi.mock('mammoth/mammoth.browser', () => ({
  default: { convertToHtml: async () => ({ value: '<h2>Hello Docx</h2><p>Body.</p>' }) },
}));

const DOCX_MIME =
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document';

function mkArt(over: Partial<ArtifactView>): ArtifactView {
  return {
    id: 'a1', thread_id: 't1', name: 'f', version: 1, content_hash: 'h1',
    mime: 'text/plain', size_bytes: 1, created_by: 'agent', created_at: 1,
    supersedes: null, _pinned_from_project: false, ...over,
  };
}

function setupStore(art: ArtifactView, contentType: string) {
  useStore.setState({
    activeThreadId: 't1',
    chatThreads: new Map([
      ['t1', { id: 't1', title: 'T1', participants: ['a'], created_at: 1, last_active_at: 1 }],
    ]),
    artifactsByThread: new Map([['t1', [art]]]),
    selectedArtifactId: art.id,
    artifactDrawerCollapsed: false,
  });
  global.fetch = vi.fn((url: unknown) => {
    const u = String(url);
    if (u.endsWith('/content')) {
      return Promise.resolve({
        ok: true,
        headers: { get: (k: string) => (k.toLowerCase() === 'content-type' ? contentType : null) },
        blob: async () => new Blob(['BYTES'], { type: contentType }),
      }) as unknown as Promise<Response>;
    }
    return Promise.resolve({
      ok: true, json: async () => ({ thread_id: 't1', artifacts: [art] }),
    }) as unknown as Promise<Response>;
  }) as unknown as typeof fetch;
}

beforeEach(() => {
  localStorage.clear();
  // jsdom lacks object-URL helpers used by the pdf branch.
  (globalThis.URL as unknown as { createObjectURL: () => string }).createObjectURL = vi.fn(() => 'blob:mock-url');
  (globalThis.URL as unknown as { revokeObjectURL: () => void }).revokeObjectURL = vi.fn();
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe('AD-1074b ArtifactViewer document rendering', () => {
  it('renders a .docx as sanitized HTML via mammoth', async () => {
    setupStore(mkArt({ id: 'd1', name: 'report.docx', mime: DOCX_MIME }), DOCX_MIME);
    render(<ArtifactDrawer />);
    await waitFor(() => {
      expect(screen.getByTestId('artifact-docx')).toBeInTheDocument();
    });
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent('Hello Docx');
  });

  it('renders a .pdf in the native iframe viewer', async () => {
    setupStore(mkArt({ id: 'p1', name: 'report.pdf', mime: 'application/pdf' }), 'application/pdf');
    render(<ArtifactDrawer />);
    await waitFor(() => {
      const frame = screen.getByTestId('artifact-pdf') as HTMLIFrameElement;
      expect(frame.getAttribute('src')).toBe('blob:mock-url');
    });
  });
});
