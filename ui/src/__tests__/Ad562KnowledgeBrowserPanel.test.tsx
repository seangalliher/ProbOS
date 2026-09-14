/**
 * AD-562: KnowledgeBrowserPanel tests.
 *
 * Mocks heavy children (RecordsGraphView pulls react-force-graph-3d).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, act, cleanup, waitFor } from '@testing-library/react';

vi.mock('../components/knowledge/RecordsGraphView', () => ({
  default: () => <div data-testid="mock-records-graph-view" />,
}));

import KnowledgeBrowserPanel from '../components/KnowledgeBrowserPanel';
import { useStore } from '../store/useStore';
import { DEFAULT_KNOWLEDGE_BROWSER_FILTERS } from '../components/knowledge/types';
import type { KnowledgeResource } from '../store/useStore';
import { RESOURCE_TIMEOUT_MS } from '../utils/resourceState';

function jsonResp(body: any, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function reset() {
  useStore.getState().closeKnowledgeBrowser();
  useStore.setState({
    knowledgeBrowserOpen: false,
    knowledgeBrowserView: 'list',
    knowledgeBrowserSelectedPath: null,
    knowledgeBrowserFilters: { ...DEFAULT_KNOWLEDGE_BROWSER_FILTERS },
    knowledgeBrowserEntries: [],
    knowledgeBrowserSelectedDoc: null,
    knowledgeBrowserBacklinks: null,
    knowledgeBrowserGraphData: null,
    knowledgeBrowserTimeline: null,
    knowledgeBrowserLoading: false,
  });
}

function graphPayload() {
  return { nodes: [], edges: [], generated_at: 1, node_count: 0, edge_count: 0 };
}

function timelinePayload() {
  return { buckets: [{ date: '2026-09-13', count: 1, by_department: { science: 1 } }], total: 1, bucket: 'day' };
}

function routeResource(url: string): KnowledgeResource {
  const pathname = new URL(url, 'http://localhost').pathname;
  if (pathname.startsWith('/api/records/documents/')) return 'document';
  if (pathname.startsWith('/api/records/backlinks/')) return 'backlinks';
  if (pathname === '/api/records/browse') return 'browse';
  if (pathname === '/api/records/graph') return 'graph';
  if (pathname === '/api/records/timeline') return 'timeline';
  throw new Error(`Unexpected knowledge request: ${url}`);
}

function successPayload(url: string): unknown {
  const resource = routeResource(url);
  const path = decodeURIComponent(new URL(url, 'http://localhost').pathname.split('/').slice(4).join('/'));
  switch (resource) {
    case 'browse': return { documents: [{ path: 'x.md', frontmatter: { author: 'spock', topic_slug: 'record' } }], count: 1, filters_applied: {} };
    case 'graph': return graphPayload();
    case 'timeline': return timelinePayload();
    case 'document': return { path, frontmatter: {}, content: `Body for ${path}` };
    case 'backlinks': return { path, references: [{ kind: 'wikilink', target: 'source', raw_match: '[[source]]' }], referenced_by: ['source.md'], suggested: [{ path: 'suggested.md', similarity: 0.8 }] };
  }
}

function mockReads(override?: (resource: KnowledgeResource, url: string) => Response | Promise<Response> | undefined) {
  return vi.spyOn(global, 'fetch').mockImplementation(async input => {
    const url = String(input);
    return override?.(routeResource(url), url) ?? jsonResp(successPayload(url));
  });
}

function deferredResponse() {
  let resolve!: (response: Response) => void;
  const promise = new Promise<Response>(complete => { resolve = complete; });
  return { promise, resolve };
}

async function openPanel(path?: string): Promise<void> {
  await act(async () => {
    await useStore.getState().openKnowledgeBrowser();
    if (path) await useStore.getState().selectKnowledgeBrowserEntry(path);
  });
  render(<KnowledgeBrowserPanel />);
}

describe('KnowledgeBrowserPanel (AD-562)', () => {
  beforeEach(reset);
  afterEach(() => { cleanup(); reset(); vi.restoreAllMocks(); vi.useRealTimers(); });

  it('renders nothing when knowledgeBrowserOpen=false', () => {
    render(<KnowledgeBrowserPanel />);
    expect(screen.queryByTestId('knowledge-browser-panel')).toBeNull();
  });

  it('renders panel + four view-mode tabs + close button when open', () => {
    useStore.setState({ knowledgeBrowserOpen: true });
    render(<KnowledgeBrowserPanel />);
    expect(screen.getByTestId('knowledge-browser-panel')).toBeTruthy();
    expect(screen.getByTestId('knowledge-tab-list')).toBeTruthy();
    expect(screen.getByTestId('knowledge-tab-reader')).toBeTruthy();
    expect(screen.getByTestId('knowledge-tab-graph')).toBeTruthy();
    expect(screen.getByTestId('knowledge-tab-timeline')).toBeTruthy();
    expect(screen.getByTestId('knowledge-close')).toBeTruthy();
  });

  it('opening triggers fetches of /browse and /graph and /timeline', async () => {
    const fetchMock = mockReads();
    await act(async () => {
      await useStore.getState().openKnowledgeBrowser();
    });
    const calls = fetchMock.mock.calls.map(c => String(c[0]));
    expect(calls.some(u => u.startsWith('/api/records/browse'))).toBe(true);
    expect(calls.some(u => u.includes('/api/records/graph?include_quality=true&include_suggested=true'))).toBe(true);
    expect(calls.some(u => u.includes('/api/records/timeline?bucket=day'))).toBe(true);
  });

  it('shows an accessible unavailable status instead of empty timeline data when the timeline request returns 503 (issue #1368)', async () => {
    const fetchMock = vi.spyOn(global, 'fetch').mockImplementation(async (url) => {
      const pathname = new URL(String(url), 'http://localhost').pathname;
      if (pathname === '/api/records/browse') {
        return jsonResp({ documents: [], count: 0, filters_applied: {} });
      }
      if (pathname === '/api/records/graph') {
        return jsonResp(graphPayload());
      }
      if (pathname === '/api/records/timeline') {
        return jsonResp({ error: 'Knowledge Browser not available' }, 503);
      }
      throw new Error(`Unexpected knowledge browser request: ${String(url)}`);
    });

    await act(async () => {
      await useStore.getState().openKnowledgeBrowser();
    });
    render(<KnowledgeBrowserPanel />);
    fireEvent.click(screen.getByTestId('knowledge-tab-timeline'));

    const calls = fetchMock.mock.calls.map(call => String(call[0]));
    expect(calls).toContain('/api/records/timeline?bucket=day');
    expect(screen.queryByText('No timeline data')).toBeNull();
    expect(screen.getByRole('status').textContent).toMatch(/unavailable|not available/i);
  });

  it('ESC keypress closes the panel', async () => {
    vi.spyOn(global, 'fetch').mockImplementation(() => Promise.resolve(jsonResp({ documents: [] })));
    useStore.setState({ knowledgeBrowserOpen: true });
    render(<KnowledgeBrowserPanel />);
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(useStore.getState().knowledgeBrowserOpen).toBe(false);
  });

  it('refresh button re-invokes fetches', async () => {
    const fetchMock = vi.spyOn(global, 'fetch').mockImplementation(() => Promise.resolve(jsonResp({ documents: [] })));
    useStore.setState({ knowledgeBrowserOpen: true });
    render(<KnowledgeBrowserPanel />);
    fetchMock.mockClear();
    await act(async () => {
      fireEvent.click(screen.getByTestId('knowledge-refresh'));
    });
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled();
    });
  });

  it('switching tabs changes the rendered view after successful empty reads', async () => {
    mockReads(resource => resource === 'browse' ? jsonResp({ documents: [], count: 0, filters_applied: {} }) : undefined);
    await openPanel();
    expect(screen.getByTestId('knowledge-list-empty')).toBeTruthy();
    fireEvent.click(screen.getByTestId('knowledge-tab-graph'));
    expect(screen.getByTestId('mock-records-graph-view')).toBeTruthy();
  });

  it('backlinks rail hidden when no selection', () => {
    useStore.setState({ knowledgeBrowserOpen: true, knowledgeBrowserView: 'reader', knowledgeBrowserSelectedPath: null });
    render(<KnowledgeBrowserPanel />);
    expect(screen.queryByTestId('knowledge-backlinks-rail')).toBeNull();
  });

  it('backlinks rail visible when reader view + successfully loaded selection', async () => {
    mockReads();
    await openPanel('x.md');
    expect(screen.getByTestId('knowledge-backlinks-rail')).toBeTruthy();
  });

  it('keeps list and reader usable when graph, timeline and backlinks return 503', async () => {
    const fetchMock = mockReads(resource => ['graph', 'timeline', 'backlinks'].includes(resource)
      ? jsonResp({ error: 'Knowledge Browser not available' }, 503) : undefined);
    await openPanel();
    expect(useStore.getState().knowledgeBrowserResources.browse.status).toBe('ready');
    expect(screen.getByRole('region', { name: 'Browse resource' }).textContent).toContain('x.md');
    expect(screen.getByLabelText('Knowledge partial results').textContent).toContain('Degraded');
    await act(async () => { await useStore.getState().selectKnowledgeBrowserEntry('x.md'); });
    expect(screen.getByText('Body for x.md')).toBeTruthy();
    expect(screen.getByRole('status', { name: 'Backlinks status' }).textContent).toMatch(/unavailable/i);
    expect(screen.queryByTestId('knowledge-backlinks-rail')).toBeNull();
    expect(fetchMock.mock.calls.filter(call => routeResource(String(call[0])) === 'backlinks')).toHaveLength(1);
    fireEvent.click(screen.getByTestId('knowledge-tab-graph'));
    expect(screen.queryByTestId('mock-records-graph-view')).toBeNull();
    expect(screen.getByRole('status', { name: 'Graph status' }).textContent).toMatch(/unavailable/i);
  });

  it.each(['author', 'department', 'classification', 'created', 'updated', 'topic_slug', 'revision_count', 'tags'])(
    'renders successful browse and document payloads with nullable %s frontmatter', async field => {
      mockReads((resource, url) => {
        const frontmatter = { [field]: null };
        if (resource === 'browse') return jsonResp({ documents: [{ path: 'x.md', frontmatter }], count: 1, filters_applied: {} });
        if (resource === 'document') return jsonResp({ path: 'x.md', frontmatter, content: 'A real record body' });
        return jsonResp(successPayload(url));
      });
      await openPanel();
      expect(useStore.getState().knowledgeBrowserResources.browse.status).toBe('ready');
      expect(screen.getByRole('region', { name: 'Browse resource' })).toHaveTextContent('x.md');
      await act(async () => { await useStore.getState().selectKnowledgeBrowserEntry('x.md'); });
      expect(useStore.getState().knowledgeBrowserResources.document.status).toBe('ready');
      expect(screen.getByText('A real record body')).toBeInTheDocument();
    },
  );

  it.each([404, 410])('clears the prior document when the real not-found-or-denied envelope arrives with HTTP %i', async status => {
    let missing = false;
    mockReads(resource => resource === 'document' && missing
      ? jsonResp({ error: 'Not found or access denied', availability: {
        state: 'failed', code: 'records.not_found', message: 'Not found or access denied', retryable: false,
      } }, status) : undefined);
    await openPanel('x.md');
    expect(screen.getByText('Body for x.md')).toBeInTheDocument();
    missing = true;
    await act(async () => { await useStore.getState().retryKnowledgeResource('document'); });
    expect(useStore.getState().knowledgeBrowserSelectedDoc).toBeNull();
    expect(screen.queryByText('Body for x.md')).toBeNull();
    expect(screen.getByRole('status', { name: 'Document status' })).toHaveTextContent('Request failed.');
  });

  it.each([
    [503, { availability: { state: 'disabled', code: 'knowledge_disabled', message: 'Disabled by configuration', retryable: false } }, 'disabled', false],
    [401, { error: 'private exception' }, 'denied', false],
    [403, { detail: 'private exception' }, 'denied', false],
    [500, { error: 'private exception: enable unsafe module' }, 'failed', true],
    [200, { buckets: [], total: '0' }, 'failed', true],
  ] as const)('renders controlled timeline status for HTTP %s', async (status, payload, expected, retryable) => {
    mockReads(resource => resource === 'timeline' ? jsonResp(payload, status) : undefined);
    await openPanel();
    fireEvent.click(screen.getByTestId('knowledge-tab-timeline'));
    expect(screen.getByRole('status', { name: 'Timeline status' }).textContent?.toLowerCase()).toContain(expected);
    expect(screen.queryByText('No timeline data')).toBeNull();
    expect(screen.queryByText(/private exception|unsafe module/)).toBeNull();
    expect(screen.queryByRole('button', { name: 'Retry Timeline' }) !== null).toBe(retryable);
  });

  it('renders true empty timeline, reader and backlinks only after successful responses', async () => {
    mockReads((resource, url) => {
      if (resource === 'timeline') return jsonResp({ buckets: [], total: 0, bucket: 'day' });
      if (resource === 'document') return jsonResp({ path: 'x.md', frontmatter: {}, content: '' });
      if (resource === 'backlinks') return jsonResp({ path: 'x.md', references: [], referenced_by: [], suggested: [] });
      return jsonResp(successPayload(url));
    });
    await openPanel('x.md');
    expect(screen.getByTestId('reader-empty-content')).toBeTruthy();
    expect(screen.getByTestId('knowledge-backlinks-rail')).toBeTruthy();
    expect(screen.queryByRole('status')).toBeNull();
    fireEvent.click(screen.getByTestId('knowledge-tab-timeline'));
    expect(screen.getByText('No timeline data')).toBeTruthy();
    expect(useStore.getState().knowledgeBrowserResources.timeline.status).toBe('empty');
  });

  it.each(['browse', 'graph', 'timeline', 'document', 'backlinks'] as const)('fails malformed %s without calling it empty', async resource => {
    mockReads(target => target === resource ? jsonResp({}) : undefined);
    await openPanel('x.md');
    expect(useStore.getState().knowledgeBrowserResources[resource]).toMatchObject({ status: 'failed', data: null });
    const view = resource === 'browse' ? 'list' : resource === 'document' || resource === 'backlinks' ? 'reader' : resource;
    fireEvent.click(screen.getByTestId(`knowledge-tab-${view}`));
    const label = resource[0].toUpperCase() + resource.slice(1);
    expect(screen.getByRole('status', { name: `${label} status` }).textContent).toMatch(/failed/i);
  });

  it.each([
    ['browse', { documents: [{ path: 'bad.md', frontmatter: { tags: [3] } }], count: 1, filters_applied: {} }],
    ['graph', { ...graphPayload(), nodes: [{}], node_count: 1 }],
    ['graph', { ...graphPayload(), edges: [{}], edge_count: 1 }],
    ['timeline', { buckets: [{ date: '2026-09-13', count: 1, by_department: null }], total: 1, bucket: 'day' }],
    ['timeline', { buckets: [], total: 2, bucket: 'day' }],
    ['document', { path: 'other.md', frontmatter: {}, content: 'Wrong identity' }],
    ['backlinks', { path: 'x.md', references: [], referenced_by: [], suggested: [{ path: 'x', similarity: 'bad' }] }],
  ] as const)('rejects malformed nested %s payload %j', async (resource, payload) => {
    mockReads(target => target === resource ? jsonResp(payload) : undefined);
    await openPanel('x.md');
    expect(useStore.getState().knowledgeBrowserResources[resource]).toMatchObject({ status: 'failed', data: null });
  });

  it.each(['browse', 'graph', 'timeline', 'document', 'backlinks'] as const)('retries only %s and clears stale state on recovery', async resource => {
    let failing = false;
    const fetchMock = mockReads(target => target === resource && failing ? jsonResp({ error: 'not available' }, 503) : undefined);
    await openPanel('x.md');
    const good = useStore.getState().knowledgeBrowserResources[resource];
    expect(good.data).not.toBeNull();
    failing = true;
    await act(async () => { await useStore.getState().retryKnowledgeResource(resource); });
    expect(useStore.getState().knowledgeBrowserResources[resource]).toMatchObject({ status: 'unavailable', stale: true, data: good.data, observedAt: good.observedAt });
    const view = resource === 'browse' ? 'list' : resource === 'document' || resource === 'backlinks' ? 'reader' : resource;
    fireEvent.click(screen.getByTestId(`knowledge-tab-${view}`));
    const label = resource[0].toUpperCase() + resource.slice(1);
    expect(screen.getByRole('status', { name: `${label} status` }).textContent).toContain('Stale');
    if (resource === 'timeline') expect(screen.getByTestId('timeline-bar-2026-09-13-science')).toBeTruthy();
    if (resource === 'document') expect(screen.getByText('Body for x.md')).toBeTruthy();
    if (resource === 'backlinks') expect(screen.getByTestId('backlink-incoming').textContent).toBe('source.md');
    fetchMock.mockClear();
    failing = false;
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: `Retry ${label}` })); });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(routeResource(String(fetchMock.mock.calls[0][0]))).toBe(resource);
    expect(useStore.getState().knowledgeBrowserResources[resource]).toMatchObject({ status: good.status, stale: false });
    expect(screen.queryByRole('status', { name: `${label} status` })).toBeNull();
  });

  it('does not render an old empty timeline as currently empty after failure', async () => {
    let failing = false;
    mockReads(resource => resource === 'timeline' ? (failing
      ? jsonResp({ error: 'unavailable' }, 503)
      : jsonResp({ buckets: [], total: 0, bucket: 'day' })) : undefined);
    await openPanel();
    fireEvent.click(screen.getByTestId('knowledge-tab-timeline'));
    expect(screen.getByText('No timeline data')).toBeTruthy();
    failing = true;
    await act(async () => { await useStore.getState().retryKnowledgeResource('timeline'); });
    expect(screen.queryByText('No timeline data')).toBeNull();
    expect(screen.getByRole('status').textContent).toMatch(/stale.*empty/i);
  });

  it.each([401, 403])('removes cached reader and backlinks after authorization failure %s', async status => {
    let denied = false;
    mockReads(resource => denied && ['document', 'backlinks'].includes(resource) ? jsonResp({ detail: 'denied' }, status) : undefined);
    await openPanel('x.md');
    expect(screen.getByText('Body for x.md')).toBeTruthy();
    expect(screen.getByTestId('backlink-incoming')).toBeTruthy();
    denied = true;
    await act(async () => { await useStore.getState().refreshKnowledgeBrowser(); });
    expect(screen.queryByText('Body for x.md')).toBeNull();
    expect(screen.queryByTestId('backlink-incoming')).toBeNull();
    expect(useStore.getState().knowledgeBrowserSelectedDoc).toBeNull();
    expect(useStore.getState().knowledgeBrowserBacklinks).toBeNull();
    expect(screen.getByRole('status', { name: 'Document status' }).textContent).toMatch(/denied/i);
  });

  it('global refresh fetches the current document and backlinks as well as browse resources', async () => {
    const fetchMock = mockReads();
    await openPanel('x.md');
    fetchMock.mockClear();
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Refresh' })); });
    expect(fetchMock.mock.calls.map(call => routeResource(String(call[0]))).sort()).toEqual(['backlinks', 'browse', 'document', 'graph', 'timeline']);
    expect(screen.getByText('Body for x.md')).toBeTruthy();
    expect(screen.getByTestId('backlink-suggested').textContent).toContain('0.80');
  });

  it('ignores old filter results and never retains data from different filters', async () => {
    const late = deferredResponse();
    let delayOld = false;
    const fetchMock = mockReads((resource, url) => resource === 'browse' && delayOld && !url.includes('author=new') ? late.promise : undefined);
    await openPanel();
    delayOld = true;
    let oldRequest!: Promise<void>;
    act(() => { oldRequest = useStore.getState().retryKnowledgeResource('browse'); });
    expect(useStore.getState().knowledgeBrowserResources.browse.refreshing).toBe(true);
    await act(async () => { useStore.getState().setKnowledgeBrowserFilters({ author: 'new' }); });
    expect(fetchMock.mock.calls.some(call => String(call[0]).includes('author=new'))).toBe(true);
    await act(async () => {
      late.resolve(jsonResp({ documents: [{ path: 'old.md', frontmatter: {} }], count: 1, filters_applied: {} }));
      await oldRequest;
    });
    expect(useStore.getState().knowledgeBrowserEntries[0].path).toBe('x.md');
    expect(useStore.getState().knowledgeBrowserResources.browse.identity).toContain('author=new');
    fetchMock.mockImplementation(async () => jsonResp({ error: 'unavailable' }, 503));
    await act(async () => { useStore.getState().setKnowledgeBrowserFilters({ author: 'other' }); });
    expect(useStore.getState().knowledgeBrowserResources.browse).toMatchObject({ status: 'unavailable', data: null, stale: false });
    expect(useStore.getState().knowledgeBrowserEntries).toEqual([]);
  });

  it('clears the previous document immediately and ignores a late old selection', async () => {
    const oldDoc = deferredResponse();
    const oldLinks = deferredResponse();
    const fetchMock = mockReads((resource, url) => url.includes('old.md')
      ? resource === 'document' ? oldDoc.promise : resource === 'backlinks' ? oldLinks.promise : undefined
      : undefined);
    await openPanel('x.md');
    let oldRequest!: Promise<void>;
    act(() => { oldRequest = useStore.getState().selectKnowledgeBrowserEntry('old.md'); });
    expect(fetchMock.mock.calls.filter(call => String(call[0]).includes('old.md'))).toHaveLength(2);
    expect(screen.queryByText('Body for x.md')).toBeNull();
    expect(screen.getByRole('status', { name: 'Document status' }).textContent).toMatch(/loading/i);
    expect(screen.queryByTestId('knowledge-reader-empty')).toBeNull();
    await act(async () => { await useStore.getState().selectKnowledgeBrowserEntry('new.md'); });
    await act(async () => {
      oldDoc.resolve(jsonResp({ path: 'old.md', frontmatter: {}, content: 'Late old body' }));
      oldLinks.resolve(jsonResp({ path: 'old.md', references: [], referenced_by: ['late.md'], suggested: [] }));
      await oldRequest;
    });
    expect(screen.getByText('Body for new.md')).toBeTruthy();
    expect(screen.queryByText('Late old body')).toBeNull();
    expect(screen.queryByText('late.md')).toBeNull();
    expect(useStore.getState().knowledgeBrowserSelectedPath).toBe('new.md');
  });

  it('invalidates all requests on close, ignores late responses and permits re-entry', async () => {
    vi.useFakeTimers();
    const late = deferredResponse();
    let hanging = false;
    const fetchMock = mockReads(() => hanging ? late.promise : undefined);
    await openPanel('x.md');
    hanging = true;
    fetchMock.mockClear();
    let refresh!: Promise<void>;
    act(() => { refresh = useStore.getState().refreshKnowledgeBrowser(); });
    expect(fetchMock).toHaveBeenCalledTimes(5);
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Close' })); await refresh; });
    expect(fetchMock.mock.calls.every(call => (call[1]?.signal as AbortSignal).aborted)).toBe(true);
    await act(async () => { late.resolve(jsonResp(timelinePayload())); });
    expect(screen.queryByTestId('knowledge-browser-panel')).toBeNull();
    expect(Object.values(useStore.getState().knowledgeBrowserResources).every(state => state.status === 'idle' && state.data === null)).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
    hanging = false;
    await act(async () => { await useStore.getState().openKnowledgeBrowser(); });
    expect(useStore.getState().knowledgeBrowserResources.timeline.status).toBe('ready');
    expect(useStore.getState().knowledgeBrowserSelectedDoc).toBeNull();
  });

  it('bounds hung timeline reads without hiding browse or starting background polling', async () => {
    vi.useFakeTimers();
    const fetchMock = mockReads(resource => resource === 'timeline' ? new Promise<Response>(() => {}) : undefined);
    let opening!: Promise<void>;
    await act(async () => { opening = useStore.getState().openKnowledgeBrowser(); });
    render(<KnowledgeBrowserPanel />);
    expect(useStore.getState().knowledgeBrowserResources.browse.status).toBe('ready');
    expect(fetchMock.mock.calls.filter(call => routeResource(String(call[0])) === 'timeline')).toHaveLength(1);
    fireEvent.click(screen.getByTestId('knowledge-tab-timeline'));
    expect(screen.getByRole('status', { name: 'Timeline status' }).textContent).toMatch(/loading/i);
    expect(screen.queryByText('No timeline data')).toBeNull();
    await act(async () => { await vi.advanceTimersByTimeAsync(RESOURCE_TIMEOUT_MS); await opening; });
    expect(screen.getByRole('status', { name: 'Timeline status' }).textContent).toMatch(/unavailable/i);
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(useStore.getState().knowledgeBrowserLoading).toBe(false);
  });

  it('clears empty selection, ignores closed refresh and re-enters on explicit selection', async () => {
    const fetchMock = mockReads();
    await openPanel('x.md');
    fetchMock.mockClear();
    await act(async () => { await useStore.getState().selectKnowledgeBrowserEntry(''); });
    expect(useStore.getState().knowledgeBrowserSelectedDoc).toBeNull();
    expect(screen.getByTestId('knowledge-reader-empty')).toBeTruthy();
    expect(fetchMock).not.toHaveBeenCalled();
    await act(async () => {
      useStore.getState().closeKnowledgeBrowser();
      await useStore.getState().refreshKnowledgeBrowser();
    });
    expect(fetchMock).not.toHaveBeenCalled();
    await act(async () => { await useStore.getState().selectKnowledgeBrowserEntry('x.md'); });
    expect(useStore.getState().knowledgeBrowserOpen).toBe(true);
    expect(useStore.getState().knowledgeBrowserSelectedPath).toBe('x.md');
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
