/* AD-597a: McpAppBridge — JSON-RPC dispatcher between host and sandboxed iframe. */

import type { JsonRpcEnvelope, McpAppBridgeOptions } from './types';

const HOST_TO_APP_METHODS = new Set([
  'ui/initialize',
  'ui/notifications/tool-input',
  'ui/notifications/tool-result',
]);

export class McpAppBridge {
  private iframe: HTMLIFrameElement;
  private endpoint: string;
  private onUiMessage?: (payload: unknown) => void;
  private onUpdateModelContext?: (payload: unknown) => void;
  private listener: (event: MessageEvent) => void;
  private disposed = false;

  constructor(opts: McpAppBridgeOptions) {
    this.iframe = opts.iframe;
    this.endpoint = opts.jsonrpcEndpoint ?? '/api/mcp/jsonrpc';
    this.onUiMessage = opts.onUiMessage;
    this.onUpdateModelContext = opts.onUpdateModelContext;
    this.listener = (event: MessageEvent) => this.handleMessage(event);
    window.addEventListener('message', this.listener);
  }

  /** Send a host -> iframe message via postMessage. */
  postToApp(envelope: JsonRpcEnvelope): void {
    if (this.disposed) return;
    if (!HOST_TO_APP_METHODS.has(envelope.method ?? '')) {
      return;
    }
    const win = this.iframe.contentWindow;
    if (!win) return;
    win.postMessage(envelope, '*');
  }

  /** Convenience wrappers for the host -> iframe lifecycle messages. */
  initialize(): void {
    this.postToApp({ jsonrpc: '2.0', method: 'ui/initialize', params: {} });
  }

  sendToolInput(input: unknown): void {
    this.postToApp({
      jsonrpc: '2.0',
      method: 'ui/notifications/tool-input',
      params: { input } as Record<string, unknown>,
    });
  }

  sendToolResult(result: unknown): void {
    this.postToApp({
      jsonrpc: '2.0',
      method: 'ui/notifications/tool-result',
      params: { result } as Record<string, unknown>,
    });
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    window.removeEventListener('message', this.listener);
  }

  private async handleMessage(event: MessageEvent): Promise<void> {
    if (this.disposed) return;
    // Only accept messages from our iframe's window.
    if (this.iframe.contentWindow !== event.source) return;
    const data = event.data as JsonRpcEnvelope | undefined;
    if (!data || data.jsonrpc !== '2.0' || typeof data.method !== 'string') {
      return;
    }
    const method = data.method;
    if (method === 'tools/call') {
      await this.forwardToolCall(data);
      return;
    }
    if (method === 'ui/message') {
      this.onUiMessage?.(data.params);
      return;
    }
    if (method === 'ui/update-model-context') {
      this.onUpdateModelContext?.(data.params);
      return;
    }
  }

  private async forwardToolCall(envelope: JsonRpcEnvelope): Promise<void> {
    try {
      const response = await fetch(this.endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(envelope),
      });
      const body = (await response.json()) as JsonRpcEnvelope;
      this.postToApp({
        jsonrpc: '2.0',
        method: 'ui/notifications/tool-result',
        params: { result: body.result, error: body.error } as Record<string, unknown>,
      });
    } catch (err) {
      this.postToApp({
        jsonrpc: '2.0',
        method: 'ui/notifications/tool-result',
        params: { error: { code: -32000, message: String(err) } } as Record<string, unknown>,
      });
    }
  }
}
