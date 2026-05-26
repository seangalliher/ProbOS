/** AD-797 (Wave 197) vitest — inline ArtifactCard parses a stub line and
 * dispatches selectArtifact + uncollapses the drawer on click. */
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent } from '@testing-library/react';
import { useStore, type ArtifactView } from '../store/useStore';
import { ArtifactCard } from '../components/artifacts/ArtifactCard';
import { parseArtifactStub } from '../components/artifacts/artifactApi';

const ART: ArtifactView = {
  id: 'a1', thread_id: 't1', name: 'helper.py', version: 1,
  content_hash: 'h1', mime: 'text/x-python', size_bytes: 73,
  created_by: 'agent', created_at: 1, supersedes: null,
  _pinned_from_project: false,
};

beforeEach(() => {
  useStore.setState({
    artifactsByThread: new Map([['t1', [ART]]]),
    selectedArtifactId: null,
    artifactDrawerCollapsed: true,
  });
});

afterEach(() => { cleanup(); });

describe('ArtifactCard inline', () => {
  it('parses the stub line and renders a card resolved against the thread', () => {
    const stub = parseArtifactStub('[Artifact: helper.py v1 - 73 lines, text/x-python]');
    expect(stub).not.toBeNull();
    expect(stub!.name).toBe('helper.py');
    expect(stub!.version).toBe(1);
    expect(stub!.lineCount).toBe(73);
    expect(stub!.mime).toBe('text/x-python');

    render(
      <ArtifactCard
        threadId="t1"
        name={stub!.name}
        version={stub!.version}
        lineCount={stub!.lineCount}
        mime={stub!.mime}
      />,
    );
    const card = screen.getByTestId('artifact-card');
    expect(card).toBeInTheDocument();
    expect(card).toHaveTextContent('helper.py');
    expect(card).toHaveTextContent('v1');

    fireEvent.click(card);
    const state = useStore.getState();
    expect(state.selectedArtifactId).toBe('a1');
    expect(state.artifactDrawerCollapsed).toBe(false);
  });
});
