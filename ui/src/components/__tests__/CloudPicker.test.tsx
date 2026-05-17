import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, fireEvent, cleanup, waitFor, screen } from '@testing-library/react';

import { CloudPicker } from '../CloudPicker';

// AD-720c: CloudPicker component tests.

type FetchHandler = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

function installFetch(handler: FetchHandler) {
  globalThis.fetch = vi.fn(handler) as unknown as typeof fetch;
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

describe('CloudPicker (AD-720c)', () => {
  beforeEach(() => {
    // Stub window.open so authorize tests don't actually open popups.
    vi.spyOn(window, 'open').mockImplementation(() => null);
  });
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('renders only enabled providers', () => {
    render(
      <CloudPicker
        open
        onClose={vi.fn()}
        onAttached={vi.fn()}
        enabledProviders={['google_drive']}
      />,
    );
    expect(screen.getByTestId('cloud-picker-provider-google_drive')).toBeTruthy();
    expect(screen.queryByTestId('cloud-picker-provider-onedrive')).toBeNull();
    expect(screen.queryByTestId('cloud-picker-provider-dropbox')).toBeNull();
  });

  it('returns nothing when open=false', () => {
    const { container } = render(
      <CloudPicker open={false} onClose={vi.fn()} onAttached={vi.fn()} />,
    );
    expect(container.querySelector('[data-testid="cloud-picker-modal"]')).toBeNull();
  });

  it('authorize flow opens popup and switches to file list on postMessage', async () => {
    installFetch(async (input) => {
      const url = typeof input === 'string' ? input : input.toString();
      if (url.endsWith('/api/cloud-pickers/google_drive/start')) {
        return jsonResponse({ auth_url: 'https://example/auth', state: 'st-1' });
      }
      if (url.includes('/api/cloud-pickers/google_drive/files')) {
        return jsonResponse({
          files: [
            { id: 'f1', name: 'a.pdf', mime: 'application/pdf', size_bytes: 100, modified_at: '' },
          ],
          next_page_token: null,
        });
      }
      return new Response('', { status: 404 });
    });
    render(
      <CloudPicker open onClose={vi.fn()} onAttached={vi.fn()} />,
    );
    fireEvent.click(screen.getByTestId('cloud-picker-provider-google_drive'));
    fireEvent.click(screen.getByTestId('cloud-picker-authorize'));
    await waitFor(() => expect(window.open).toHaveBeenCalled());
    // Simulate the popup posting back the oauth_complete message.
    window.postMessage({ type: 'oauth_complete', provider: 'google_drive' }, '*');
    await waitFor(() =>
      expect(screen.getByTestId('cloud-picker-file-list')).toBeTruthy(),
    );
    await waitFor(() => expect(screen.getByTestId('cloud-picker-file-f1')).toBeTruthy());
  });

  it('honest-degrades with 503 banner when feature disabled', async () => {
    installFetch(async () =>
      jsonResponse({ detail: 'feature_disabled' }, 503),
    );
    render(<CloudPicker open onClose={vi.fn()} onAttached={vi.fn()} />);
    fireEvent.click(screen.getByTestId('cloud-picker-provider-google_drive'));
    fireEvent.click(screen.getByTestId('cloud-picker-authorize'));
    await waitFor(() => {
      const banner = screen.getByTestId('cloud-picker-error');
      expect(banner.textContent).toContain('feature_disabled');
    });
  });

  it('attach POSTs file_id and invokes onAttached with returned SHA ref', async () => {
    const onAttached = vi.fn();
    const onClose = vi.fn();
    let attachBody: unknown = null;
    installFetch(async (input, init) => {
      const url = typeof input === 'string' ? input : input.toString();
      if (url.endsWith('/api/cloud-pickers/google_drive/start')) {
        return jsonResponse({ auth_url: 'https://example/auth', state: 's' });
      }
      if (url.includes('/api/cloud-pickers/google_drive/files')) {
        return jsonResponse({
          files: [
            { id: 'fid', name: 'note.txt', mime: 'text/plain', size_bytes: 5, modified_at: '' },
          ],
          next_page_token: null,
        });
      }
      if (url.endsWith('/api/cloud-pickers/google_drive/attach')) {
        attachBody = init?.body ? JSON.parse(String(init.body)) : null;
        return jsonResponse({
          attachment_id: 'a'.repeat(64),
          mime: 'text/plain',
          size_bytes: 5,
          filename: 'note.txt',
        });
      }
      return new Response('', { status: 404 });
    });
    render(<CloudPicker open onClose={onClose} onAttached={onAttached} />);
    fireEvent.click(screen.getByTestId('cloud-picker-provider-google_drive'));
    fireEvent.click(screen.getByTestId('cloud-picker-authorize'));
    window.postMessage({ type: 'oauth_complete', provider: 'google_drive' }, '*');
    await waitFor(() => expect(screen.getByTestId('cloud-picker-file-fid')).toBeTruthy());
    fireEvent.click(screen.getByTestId('cloud-picker-file-fid'));
    await waitFor(() => expect(onAttached).toHaveBeenCalledTimes(1));
    expect(attachBody).toEqual({ file_id: 'fid' });
    expect(onAttached.mock.calls[0][0].attachment_id).toBe('a'.repeat(64));
    expect(onClose).toHaveBeenCalled();
  });

  it('shows reauth banner on 401 from /files', async () => {
    installFetch(async (input) => {
      const url = typeof input === 'string' ? input : input.toString();
      if (url.endsWith('/api/cloud-pickers/google_drive/start')) {
        return jsonResponse({ auth_url: 'https://example/auth', state: 's' });
      }
      if (url.includes('/api/cloud-pickers/google_drive/files')) {
        return jsonResponse({ detail: 'reauthorization_required' }, 401);
      }
      return new Response('', { status: 404 });
    });
    render(<CloudPicker open onClose={vi.fn()} onAttached={vi.fn()} />);
    fireEvent.click(screen.getByTestId('cloud-picker-provider-google_drive'));
    fireEvent.click(screen.getByTestId('cloud-picker-authorize'));
    window.postMessage({ type: 'oauth_complete', provider: 'google_drive' }, '*');
    await waitFor(() => {
      const banner = screen.getByTestId('cloud-picker-error');
      expect(banner.textContent).toMatch(/reauthorize/i);
    });
    // After 401 we go back to the provider list (authorized=false).
    expect(screen.getByTestId('cloud-picker-authorize')).toBeTruthy();
  });

  it('close button invokes onClose', () => {
    const onClose = vi.fn();
    render(<CloudPicker open onClose={onClose} onAttached={vi.fn()} />);
    fireEvent.click(screen.getByTestId('cloud-picker-close'));
    expect(onClose).toHaveBeenCalled();
  });
});
