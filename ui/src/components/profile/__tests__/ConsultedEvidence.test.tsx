import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { ConsultedEvidence } from '../ConsultedEvidence';
import { ChatMessageRow } from '../ChatMessageRow';
import { resetConsultedTraceCacheForTests } from '../../../hooks/useConsultedTrace';
import type { AgentProfileMessage } from '../../../store/types';
import {
  ConsultedEvidenceBridge, FIXTURE_REPLY_BODY, FIXTURE_REPOSITORY, OUTPUT_SENTINEL,
  SENSITIVE_SENTINEL, type FixtureThreadMessage,
} from '../../../__tests__/helpers/consultedEvidenceBridge';

const REF = 'a'.repeat(64);
const THREAD = 'thread-1';

function baseMsg(overrides: Partial<AgentProfileMessage> = {}): AgentProfileMessage {
  return {
    id: 'msg-1', role: 'agent', text: 'hello', timestamp: 1,
    threadId: THREAD, authorId: 'agent-7', metadata: { tool_trace_ref: REF },
    ...overrides,
  };
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

beforeEach(() => {
  resetConsultedTraceCacheForTests();
  vi.stubGlobal('fetch', vi.fn());
});

afterEach(() => {
  cleanup();
  resetConsultedTraceCacheForTests();
  vi.unstubAllGlobals();
});

describe('ConsultedEvidence', () => {
  it('renders nothing when no ref is present in metadata', () => {
    const { container } = render(<ConsultedEvidence msg={baseMsg({ metadata: {} })} activeThreadId={THREAD} />);
    expect(container.innerHTML).toBe('');
    expect(fetch).not.toHaveBeenCalled();
  });

  it('renders nothing when metadata itself is absent', () => {
    const { container } = render(<ConsultedEvidence msg={baseMsg({ metadata: undefined })} activeThreadId={THREAD} />);
    expect(container.innerHTML).toBe('');
  });

  it('renders nothing for a user-role message even with a ref present', () => {
    const { container } = render(<ConsultedEvidence msg={baseMsg({ role: 'user' })} activeThreadId={THREAD} />);
    expect(container.innerHTML).toBe('');
  });

  it('renders nothing when the message thread does not match the active thread', () => {
    const { container } = render(<ConsultedEvidence msg={baseMsg()} activeThreadId="other-thread" />);
    expect(container.innerHTML).toBe('');
  });

  it('renders nothing when there is no active thread at all', () => {
    const { container } = render(<ConsultedEvidence msg={baseMsg()} activeThreadId={undefined} />);
    expect(container.innerHTML).toBe('');
  });

  it('renders nothing when authorId is blank', () => {
    const { container } = render(<ConsultedEvidence msg={baseMsg({ authorId: '   ' })} activeThreadId={THREAD} />);
    expect(container.innerHTML).toBe('');
  });

  it('renders nothing and does not fetch when the explicit message id is blank', () => {
    const { container } = render(<ConsultedEvidence msg={baseMsg({ id: '   ' })} activeThreadId={THREAD} />);
    expect(container.innerHTML).toBe('');
    expect(fetch).not.toHaveBeenCalled();
  });

  it('visibly reports a malformed ref as unreadable, distinct from no-ref-at-all, without any network call', () => {
    render(<ConsultedEvidence msg={baseMsg({ metadata: { tool_trace_ref: 'not-hex-64' } })} activeThreadId={THREAD} />);
    expect(screen.getByText(/Receipt unavailable.*unreadable/i)).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });

  it('visibly reports a non-string ref value as unreadable, not as absent', () => {
    render(<ConsultedEvidence msg={baseMsg({ metadata: { tool_trace_ref: 12345 } })} activeThreadId={THREAD} />);
    expect(screen.getByText(/Receipt unavailable.*unreadable/i)).toBeInTheDocument();
  });

  it.each([
    ['an array', ['a'.repeat(64)]],
    ['an object', { toString: () => REF }],
  ])('does not coerce %s into a valid trace ref', (_label, toolTraceRef) => {
    render(<ConsultedEvidence msg={baseMsg({ metadata: { tool_trace_ref: toolTraceRef } })} activeThreadId={THREAD} />);
    expect(screen.getByText(/Receipt unavailable.*unreadable/i)).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });

  it('renders collapsed by default and does not fetch until expanded', () => {
    render(<ConsultedEvidence msg={baseMsg()} activeThreadId={THREAD} />);
    expect(screen.getByRole('button', { name: /show consulted evidence/i })).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });

  it('fetches and renders the receipt once the disclosure is expanded', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(200, {
      ref: REF, requests: ['GET /repo/README.md'], requests_total: 1, requests_omitted: 0,
      invalid_entries: 0, redacted: false, truncated: false, notice: 'Consulted evidence.',
    }));
    render(<ConsultedEvidence msg={baseMsg()} activeThreadId={THREAD} />);
    fireEvent.click(screen.getByRole('button', { name: /show consulted evidence/i }));
    await waitFor(() => expect(screen.getByText('GET /repo/README.md')).toBeInTheDocument());
    expect(screen.getByText('Consulted evidence.')).toBeInTheDocument();
    // Never a clickable/navigable target — inert list content only.
    expect(screen.queryByRole('link')).toBeNull();
  });

  it('shows "Receipt unavailable" with a retry control on failure, and recovers on retry', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(500, {}));
    render(<ConsultedEvidence msg={baseMsg()} activeThreadId={THREAD} />);
    fireEvent.click(screen.getByRole('button', { name: /show consulted evidence/i }));
    await waitFor(() => expect(screen.getByText(/receipt unavailable/i)).toBeInTheDocument());
    const retryButton = screen.getByRole('button', { name: /retry/i });

    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(200, {
      ref: REF, requests: [], requests_total: 0, requests_omitted: 0,
      invalid_entries: 0, redacted: false, truncated: false, notice: 'Recovered after retry.',
    }));
    fireEvent.click(retryButton);
    await waitFor(() => expect(screen.getByText('Recovered after retry.')).toBeInTheDocument());
    expect(screen.getByText('No requests recorded.')).toBeInTheDocument();
  });

  it('collapses and does not carry stale expanded state across a message/owner change', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(200, {
      ref: REF, requests: ['GET /a'], requests_total: 1, requests_omitted: 0,
      invalid_entries: 0, redacted: false, truncated: false, notice: 'Consulted evidence.',
    }));
    const { rerender } = render(<ConsultedEvidence msg={baseMsg()} activeThreadId={THREAD} />);
    fireEvent.click(screen.getByRole('button', { name: /show consulted evidence/i }));
    await waitFor(() => expect(screen.getByText('GET /a')).toBeInTheDocument());

    const otherRef = 'b'.repeat(64);
    rerender(<ConsultedEvidence msg={baseMsg({ id: 'msg-2', metadata: { tool_trace_ref: otherRef } })} activeThreadId={THREAD} />);
    expect(screen.getByRole('button', { name: /show consulted evidence/i })).toBeInTheDocument();
    expect(screen.queryByText('GET /a')).toBeNull();
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});

function persistedMessage(message: FixtureThreadMessage): AgentProfileMessage {
  return {
    id: message.id, threadId: message.thread_id, authorId: message.author_id,
    role: message.role as AgentProfileMessage['role'], text: message.body,
    timestamp: message.created_at, metadata: message.metadata,
  };
}

describe('ConsultedEvidence production HTTP crossing', () => {
  it.each(['inline', 'promoted', 'outbox', 'lost_ack'] as const)(
    'consumes the actual %s producer receipt through ChatMessageRow and the real hook',
    async (mode) => {
      const root = resolve(dirname(fileURLToPath(import.meta.url)), '../../../../..');
      const bridge = new ConsultedEvidenceBridge(root);
      const wireBodies: Uint8Array[] = [];
      try {
        await bridge.boot();
        vi.mocked(fetch).mockImplementation(async (input, init) => {
          if (typeof input !== 'string' || !/^\/api\/traces\/[0-9a-f]{64}\/consulted$/.test(input)) {
            throw new Error('Unexpected request outside the owned consulted endpoint');
          }
          const response = await bridge.fetchWire(input, init);
          expect(response.status).toBe(200);
          expect(response.headers.get('cache-control')).toBe('no-store');
          wireBodies.push(new Uint8Array(await response.clone().arrayBuffer()));
          // Pass the original HTTP response to the hook, without JSON reserialization.
          return response;
        });
        const started = await bridge.startTurn(mode, { query: `component ${mode} query café` });
        let delivered = started;
        if (mode !== 'inline') {
          expect(started.released).toBe(false);
          expect(started.llm_calls).toBe(1);
          const acknowledgement = started.messages[started.messages.length - 1];
          expect(acknowledgement.metadata.tool_trace_ref).toBeUndefined();
          const ack = render(<ChatMessageRow
            msg={persistedMessage(acknowledgement)} hostAgentId={started.agent}
            hostCallsign="Yeo" activeThreadId={started.thread.id}
          />);
          expect(screen.getByText(acknowledgement.body)).toBeVisible();
          expect(screen.queryByRole('button', { name: /consulted evidence/i })).toBeNull();
          expect(fetch).not.toHaveBeenCalled();
          ack.unmount();
          delivered = await bridge.releaseTurn(started.turn);
        }
        if (mode === 'outbox' || mode === 'lost_ack') {
          expect(delivered.pending).toHaveLength(1);
          const pending = delivered.pending[0] as { message_id: string; tool_trace_ref: string };
          const recovered = await bridge.recoverTurn(started.turn);
          expect(recovered.pending).toEqual([]);
          expect(recovered.recovered).toEqual(pending);
          expect(recovered.messages.find(message => message.id === pending.message_id)?.metadata.tool_trace_ref)
            .toBe(pending.tool_trace_ref);
          delivered = recovered;
        }
        const report = delivered.messages.find(message => message.body === FIXTURE_REPLY_BODY);
        if (!report || typeof report.metadata.tool_trace_ref !== 'string') {
          throw new Error('Actual stored reply is missing its producer trace ref');
        }
        const row = render(<ChatMessageRow
          msg={persistedMessage(report)} hostAgentId={delivered.agent}
          hostCallsign="Yeo" activeThreadId={report.thread_id}
        />);
        expect(screen.getByText(report.body)).toBeVisible();
        const disclosure = screen.getByRole('button', { name: /show consulted evidence/i });
        expect(disclosure).toHaveAttribute('aria-expanded', 'false');
        expect(fetch).not.toHaveBeenCalled();
        fireEvent.click(disclosure);
        await waitFor(() => expect(screen.getByText(delivered.query, { exact: false })).toBeVisible());
        expect(screen.getByText(FIXTURE_REPOSITORY, { exact: false })).toBeVisible();
        expect(fetch).toHaveBeenCalledTimes(1);
        expect(vi.mocked(fetch).mock.calls[0][0]).toBe(`/api/traces/${report.metadata.tool_trace_ref}/consulted`);
        expect(wireBodies).toHaveLength(1);
        expect(wireBodies[0].byteLength).toBeLessThanOrEqual(16_384);
        const wire = new TextDecoder().decode(wireBodies[0]);
        expect(wire).toContain(delivered.query);
        expect(wire).toContain(FIXTURE_REPOSITORY);
        expect(wire).not.toContain(SENSITIVE_SENTINEL);
        expect(wire).not.toContain(OUTPUT_SENTINEL);
        expect(row.container.textContent).not.toContain(SENSITIVE_SENTINEL);
        expect(row.container.textContent).not.toContain(OUTPUT_SENTINEL);
        expect(screen.queryByRole('link')).toBeNull();
        expect(screen.getByText(report.body).textContent).toBe(report.body);
        const after = await bridge.snapshotTurn(started.turn);
        expect(after.messages).toEqual(delivered.messages);
        expect(after.llm_calls).toBe(2);
        expect(after.tool_calls).toBe(1);
      } finally {
        cleanup();
        await bridge.stop();
      }
    },
    45_000,
  );
});
