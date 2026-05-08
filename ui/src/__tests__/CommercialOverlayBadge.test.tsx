/**
 * AD-697-1: vitest for CommercialOverlayBadge.
 */
import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, cleanup, waitFor } from '@testing-library/react';
import CommercialOverlayBadge from '../components/CommercialOverlayBadge';

const ORIG_FETCH = globalThis.fetch;

function mockFetch(payload: any, ok = true) {
  globalThis.fetch = vi.fn(async () => ({
    ok,
    json: async () => payload,
  } as Response)) as any;
}

describe('CommercialOverlayBadge (AD-697-1)', () => {
  afterEach(() => {
    cleanup();
    globalThis.fetch = ORIG_FETCH;
  });

  it('renders nothing when commercial_loaded is false', async () => {
    mockFetch({ commercial_loaded: false, providers: [], hooks: [], pre_intent_auth_hooks: [] });
    const { container } = render(<CommercialOverlayBadge />);
    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalled();
    });
    expect(container.querySelector('[data-testid="commercial-overlay-badge"]')).toBeNull();
  });

  it('renders badge with provider list when commercial_loaded is true', async () => {
    mockFetch({
      commercial_loaded: true,
      providers: ['acme-overlay'],
      hooks: ['rbac', 'sso'],
      pre_intent_auth_hooks: ['rbac'],
    });
    render(<CommercialOverlayBadge />);
    await waitFor(() => {
      const badge = screen.queryByTestId('commercial-overlay-badge');
      expect(badge).not.toBeNull();
      expect(badge!.textContent).toContain('ACME-OVERLAY');
    });
  });

  it('renders nothing when fetch fails', async () => {
    globalThis.fetch = vi.fn(async () => { throw new Error('network'); }) as any;
    const { container } = render(<CommercialOverlayBadge />);
    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalled();
    });
    expect(container.querySelector('[data-testid="commercial-overlay-badge"]')).toBeNull();
  });

  it('renders nothing when commercial_loaded but providers list empty', async () => {
    mockFetch({ commercial_loaded: true, providers: [], hooks: [], pre_intent_auth_hooks: [] });
    const { container } = render(<CommercialOverlayBadge />);
    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalled();
    });
    expect(container.querySelector('[data-testid="commercial-overlay-badge"]')).toBeNull();
  });
});
