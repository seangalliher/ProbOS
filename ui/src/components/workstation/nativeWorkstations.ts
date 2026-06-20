/** AD-1021: the OSS native-workstation registry — maps a workstation type id to
 *  its OSS-shipped React component for the AD-1022 WorkstationLauncher seam
 *  (`deps.nativeComponents`). The launcher honest-degrades any id missing from
 *  this map to a "not yet available" placeholder, so the bundle only carries the
 *  native components that have landed. `monaco` is the code/text workstation.
 *
 *  AD-1024: `mcp-app` is a thin adapter that renders the MCP-app gallery (reuses
 *  McpAppGallery; ignores typeId/doc) so the registered native `mcp-app` type
 *  renders the gallery when hosted by the AD-1023 WorkspacePanel. Built via
 *  `createElement` (not JSX) since this is a `.ts` module.
 */
import { createElement, type ComponentType } from 'react';
import { CodeWorkstation } from './CodeWorkstation';
import { McpAppGallery } from '../mcp/McpAppGallery';
import type { NativeWorkstationProps } from './WorkstationLauncher';

export const nativeWorkstations: Record<string, ComponentType<NativeWorkstationProps>> = {
  monaco: CodeWorkstation,
  // AD-1024: render the gallery (its own deps default to the real endpoint).
  'mcp-app': (_props: NativeWorkstationProps) => createElement(McpAppGallery),
};

