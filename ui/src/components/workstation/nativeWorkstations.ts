/** AD-1021: the OSS native-workstation registry — maps a workstation type id to
 *  its OSS-shipped React component for the AD-1022 WorkstationLauncher seam
 *  (`deps.nativeComponents`). The launcher honest-degrades any id missing from
 *  this map to a "not yet available" placeholder, so the bundle only carries the
 *  native components that have landed. `monaco` is the code/text workstation.
 */
import type { ComponentType } from 'react';
import { CodeWorkstation } from './CodeWorkstation';
import type { NativeWorkstationProps } from './WorkstationLauncher';

export const nativeWorkstations: Record<string, ComponentType<NativeWorkstationProps>> = {
  monaco: CodeWorkstation,
};
