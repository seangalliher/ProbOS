/** AD-1000c: Profile Service Configuration tab — the per-agent capability hub.
 *
 *  The "button on the profile card" from the Agent Customizations epic (#944/#945):
 *  a dedicated, crew-only tab that gives each agent's capabilities a first-class
 *  home instead of being buried in the Profile tab. Hosts the AD-983c/AD-1000b
 *  CapabilityPanel — the full three-axis surface (Tools · Skills · Capabilities),
 *  with tool provenance (built-in / MCP / extension) and read-only mesh-intent
 *  visibility.
 *
 *  Aligns with VS Code's Agent Customizations editor + the personnel
 *  ServiceRecord (which also mounts CapabilityPanel) — same surface, two homes:
 *  the floating profile card (here) and the Ship's Office personnel console.
 *  HXI: stroke/text only, no emoji.
 */
import { CapabilityPanel } from './CapabilityPanel';

interface Props {
  agentId: string;
  /** Optional injected fetchers, forwarded to CapabilityPanel (tests). */
  deps?: React.ComponentProps<typeof CapabilityPanel>['deps'];
}

export function ProfileServiceTab({ agentId, deps }: Props) {
  return (
    <div
      data-testid="profile-service-tab"
      style={{ padding: '10px 12px', overflowY: 'auto', height: '100%', fontSize: 12 }}
    >
      <div style={{ fontSize: 10, color: '#8888a0', letterSpacing: 1, marginBottom: 6 }}>
        SERVICE CONFIGURATION
      </div>
      <div style={{ color: '#666680', fontSize: 10, lineHeight: 1.5, marginBottom: 10 }}>
        Tools, skills, and mesh capabilities available to this agent. Tools and
        skills can be enabled per agent; mesh capabilities are ship-served and
        shown for reference.
      </div>
      <CapabilityPanel agentId={agentId} deps={deps} />
    </div>
  );
}
