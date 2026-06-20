/** AD-1024: read-only client for the MCP-app gallery (GET /api/mcp-apps).
 *
 *  Mirrors fetchServersApi (McpServersPanel): a GET 404 means "MCP App Host
 *  disabled" -> ``{apps:[], disabled:true}`` (honest-degrade, not an error);
 *  any other non-OK status throws. The gallery surfaces the boot-discovered
 *  internal + external apps that carry a launchable ``ui://`` resource.
 */

export interface McpApp {
  name: string;
  description: string;
  resource_uri: string;
  external: boolean;
  server_id: string;
}

export interface McpAppsResult {
  apps: McpApp[];
  disabled: boolean;
}

export async function fetchMcpAppsApi(): Promise<McpAppsResult> {
  const resp = await fetch('/api/mcp-apps');
  if (resp.status === 404) return { apps: [], disabled: true };
  if (!resp.ok) throw new Error(`mcp apps fetch failed: ${resp.status}`);
  const d = await resp.json();
  return { apps: Array.isArray(d?.apps) ? d.apps : [], disabled: false };
}
