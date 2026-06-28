// AD-1074a: the Output/Workspace ArtifactDrawer is mounted beside the chat in
// the agent-profile view (the Cowork experience). Source-level guard — the full
// AgentProfilePanel mount is exercised by the sibling AgentProfilePanel.*.test.
import { describe, it, expect } from 'vitest';
import source from '../components/profile/AgentProfilePanel.tsx?raw';

describe('AD-1074a AgentProfilePanel Output drawer', () => {
  it('imports the ArtifactDrawer from the artifacts module', () => {
    expect(source).toContain("from '../artifacts/ArtifactDrawer'");
  });

  it('renders the ArtifactDrawer beside ProfileChatTab in the chat tab', () => {
    expect(source).toContain('<ArtifactDrawer />');
    // The chat tab is a flex row: [chat column | drawer].
    expect(source).toContain("display: 'flex', height: '100%', minHeight: 0");
  });

  it('BF-642: suppresses the drawer in workspace rooms (WorkspaceFilesRail owns it)', () => {
    expect(source).toContain("from '../workspace/isWorkspaceRoom'");
    expect(source).toContain('{!isWorkspaceFilesRoom && <ArtifactDrawer />}');
  });
});
