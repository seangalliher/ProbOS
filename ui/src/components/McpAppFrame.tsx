/* AD-597a: McpAppFrame — sandboxed iframe wrapping an MCP App bundle. */

import { useEffect, useRef } from 'react';
import { McpAppBridge } from '../mcpApps/bridge';
import type { McpAppFrameProps } from '../mcpApps/types';

export function McpAppFrame(props: McpAppFrameProps) {
  const { resourceUri, toolName, toolInput, toolResult, external = false } = props;
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const bridgeRef = useRef<McpAppBridge | null>(null);

  const sandbox = external
    ? 'allow-scripts'
    : 'allow-scripts allow-same-origin';
  const src = '/api/mcp/resource?uri=' + encodeURIComponent(resourceUri);

  useEffect(() => {
    const iframe = iframeRef.current;
    if (!iframe) return;
    const bridge = new McpAppBridge({ iframe });
    bridgeRef.current = bridge;
    const onLoad = () => {
      bridge.initialize();
      if (toolInput !== undefined) bridge.sendToolInput(toolInput);
      if (toolResult !== undefined) bridge.sendToolResult(toolResult);
    };
    iframe.addEventListener('load', onLoad);
    return () => {
      iframe.removeEventListener('load', onLoad);
      bridge.dispose();
      bridgeRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resourceUri]);

  // Re-emit when input/result change after mount.
  useEffect(() => {
    bridgeRef.current?.sendToolInput(toolInput);
  }, [toolInput]);

  useEffect(() => {
    bridgeRef.current?.sendToolResult(toolResult);
  }, [toolResult]);

  return (
    <iframe
      ref={iframeRef}
      src={src}
      sandbox={sandbox}
      title={`mcp-app-${toolName}`}
      style={{ border: 0, width: '100%', height: '100%' }}
    />
  );
}
