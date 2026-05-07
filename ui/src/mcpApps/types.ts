/* AD-597a: MCP App bridge types. */

export interface McpAppFrameProps {
  resourceUri: string;
  toolName: string;
  toolInput?: unknown;
  toolResult?: unknown;
  external?: boolean;
}

export interface JsonRpcEnvelope {
  jsonrpc: '2.0';
  id?: string | number;
  method?: string;
  params?: Record<string, unknown>;
  result?: unknown;
  error?: { code: number; message: string };
}

export interface McpAppBridgeOptions {
  iframe: HTMLIFrameElement;
  jsonrpcEndpoint?: string;
  onUiMessage?: (payload: unknown) => void;
  onUpdateModelContext?: (payload: unknown) => void;
}
