/* AD-597a: McpAppBridge unit tests. */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { McpAppBridge } from '../mcpApps/bridge';

function makeIframe(): HTMLIFrameElement {
  const iframe = document.createElement('iframe');
  document.body.appendChild(iframe);
  return iframe;
}

describe('McpAppBridge', () => {
  let iframe: HTMLIFrameElement;
  let postSpy: ReturnType<typeof vi.spyOn>;
  let bridge: McpAppBridge;

  beforeEach(() => {
    iframe = makeIframe();
    if (iframe.contentWindow) {
      postSpy = vi.spyOn(iframe.contentWindow, 'postMessage');
    } else {
      postSpy = vi.fn() as any;
    }
  });

  afterEach(() => {
    bridge?.dispose();
    iframe.remove();
    vi.restoreAllMocks();
  });

  it('initialize() posts ui/initialize to iframe', () => {
    bridge = new McpAppBridge({ iframe });
    bridge.initialize();
    expect(postSpy).toHaveBeenCalledWith(
      expect.objectContaining({ jsonrpc: '2.0', method: 'ui/initialize' }),
      '*',
    );
  });

  it('sendToolInput posts ui/notifications/tool-input', () => {
    bridge = new McpAppBridge({ iframe });
    bridge.sendToolInput({ x: 1 });
    expect(postSpy).toHaveBeenCalledWith(
      expect.objectContaining({ method: 'ui/notifications/tool-input' }),
      '*',
    );
  });

  it('sendToolResult posts ui/notifications/tool-result', () => {
    bridge = new McpAppBridge({ iframe });
    bridge.sendToolResult({ ok: true });
    expect(postSpy).toHaveBeenCalledWith(
      expect.objectContaining({ method: 'ui/notifications/tool-result' }),
      '*',
    );
  });

  it('does not post non-allowlisted host->app methods', () => {
    bridge = new McpAppBridge({ iframe });
    bridge.postToApp({ jsonrpc: '2.0', method: 'tools/call' });
    expect(postSpy).not.toHaveBeenCalled();
  });

  it('forwards tools/call from iframe -> /api/mcp/jsonrpc', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      json: () => Promise.resolve({ jsonrpc: '2.0', result: { ok: true } }),
    });
    vi.stubGlobal('fetch', fetchMock);
    bridge = new McpAppBridge({ iframe });
    const evt = new MessageEvent('message', {
      data: { jsonrpc: '2.0', method: 'tools/call', params: { name: 'x', arguments: {} } },
      source: iframe.contentWindow,
    });
    window.dispatchEvent(evt);
    // Allow the fetch promise to resolve.
    await new Promise(r => setTimeout(r, 0));
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/mcp/jsonrpc',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('dispatches ui/message to onUiMessage', () => {
    const onUi = vi.fn();
    bridge = new McpAppBridge({ iframe, onUiMessage: onUi });
    const evt = new MessageEvent('message', {
      data: { jsonrpc: '2.0', method: 'ui/message', params: { hello: 1 } },
      source: iframe.contentWindow,
    });
    window.dispatchEvent(evt);
    expect(onUi).toHaveBeenCalledWith({ hello: 1 });
  });

  it('dispatches ui/update-model-context to onUpdateModelContext', () => {
    const onMC = vi.fn();
    bridge = new McpAppBridge({ iframe, onUpdateModelContext: onMC });
    const evt = new MessageEvent('message', {
      data: { jsonrpc: '2.0', method: 'ui/update-model-context', params: { ctx: 'a' } },
      source: iframe.contentWindow,
    });
    window.dispatchEvent(evt);
    expect(onMC).toHaveBeenCalledWith({ ctx: 'a' });
  });

  it('ignores messages whose source is not the iframe window', () => {
    const onUi = vi.fn();
    bridge = new McpAppBridge({ iframe, onUiMessage: onUi });
    const evt = new MessageEvent('message', {
      data: { jsonrpc: '2.0', method: 'ui/message', params: {} },
      source: window,
    });
    window.dispatchEvent(evt);
    expect(onUi).not.toHaveBeenCalled();
  });

  it('dispose() removes the message listener', () => {
    const onUi = vi.fn();
    bridge = new McpAppBridge({ iframe, onUiMessage: onUi });
    bridge.dispose();
    const evt = new MessageEvent('message', {
      data: { jsonrpc: '2.0', method: 'ui/message', params: {} },
      source: iframe.contentWindow,
    });
    window.dispatchEvent(evt);
    expect(onUi).not.toHaveBeenCalled();
  });

  it('ignores non-jsonrpc message data', () => {
    const onUi = vi.fn();
    bridge = new McpAppBridge({ iframe, onUiMessage: onUi });
    const evt = new MessageEvent('message', {
      data: { hello: 'plain' },
      source: iframe.contentWindow,
    });
    window.dispatchEvent(evt);
    expect(onUi).not.toHaveBeenCalled();
  });

  it('forwards fetch errors as tool-result with error envelope', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('boom')));
    bridge = new McpAppBridge({ iframe });
    const evt = new MessageEvent('message', {
      data: { jsonrpc: '2.0', method: 'tools/call', params: { name: 'x', arguments: {} } },
      source: iframe.contentWindow,
    });
    window.dispatchEvent(evt);
    await new Promise(r => setTimeout(r, 0));
    const calls = postSpy.mock.calls.map(c => c[0] as any);
    const errCall = calls.find(c => c.method === 'ui/notifications/tool-result');
    expect(errCall).toBeDefined();
    expect((errCall.params as any).error).toBeDefined();
  });
});
