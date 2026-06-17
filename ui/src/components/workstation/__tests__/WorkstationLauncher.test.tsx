// AD-1022: WorkstationLauncher tests. Lists available workstation types from
// GET /api/workstations/types and opens one. Uses the `deps` injection so no
// global fetch mock is needed and the iframe/native children are stubbed.
// HXI #3 (no emoji) asserted.
import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import {
  WorkstationLauncher,
  type WorkstationTypeView,
  type NativeWorkstationProps,
} from '../WorkstationLauncher';

const EMOJI = /\p{Extended_Pictographic}/u;

function makeTypes(): WorkstationTypeView[] {
  return [
    { id: 'monaco', label: 'Code Editor', tier: 'oss', available: true, render_kind: 'native' },
    { id: 'immersive-demo', label: 'Immersive (demo)', tier: 'commercial', available: true, render_kind: 'iframe' },
  ];
}

// Stub iframe frame (stands in for the real McpAppFrame so jsdom never mounts
// the postMessage bridge). Records the props it was rendered with.
const iframeProps: Record<string, unknown>[] = [];
function FakeIframeFrame(props: { resourceUri: string; toolName: string; external?: boolean }) {
  iframeProps.push({ ...props });
  return <div data-testid="fake-mcp-frame">{`frame:${props.resourceUri}:${String(props.external)}`}</div>;
}

function FakeMonaco({ typeId }: NativeWorkstationProps) {
  return <div data-testid="fake-monaco">{`monaco:${typeId}`}</div>;
}

afterEach(() => {
  iframeProps.length = 0;
  cleanup();
});

describe('AD-1022 WorkstationLauncher', () => {
  it('shows the loading placeholder before the fetch resolves', () => {
    const fetchTypes = vi.fn(() => new Promise<WorkstationTypeView[]>(() => {}));
    render(<WorkstationLauncher deps={{ fetchTypes }} />);
    expect(screen.getByTestId('workstation-launcher-loading')).toBeTruthy();
  });

  it('lists only available types from the API', async () => {
    const types: WorkstationTypeView[] = [
      ...makeTypes(),
      { id: 'hidden', label: 'Hidden', tier: 'commercial', available: false, render_kind: 'iframe' },
    ];
    const fetchTypes = vi.fn(async () => types);
    render(<WorkstationLauncher deps={{ fetchTypes }} />);
    await waitFor(() => screen.getByTestId('workstation-type-monaco'));
    expect(screen.getByTestId('workstation-type-immersive-demo')).toBeTruthy();
    // Unavailable types are filtered out.
    expect(screen.queryByTestId('workstation-type-hidden')).toBeNull();
    // Tier is surfaced.
    expect(screen.getByTestId('workstation-tier-immersive-demo').textContent).toContain('COMMERCIAL');
  });

  it('renders the empty state when no types are available', async () => {
    const fetchTypes = vi.fn(async () => [] as WorkstationTypeView[]);
    render(<WorkstationLauncher deps={{ fetchTypes }} />);
    await waitFor(() => screen.getByTestId('workstation-empty'));
    expect(screen.getByTestId('workstation-empty')).toBeTruthy();
  });

  it('honest-degrades a native type with no registered component', async () => {
    const fetchTypes = vi.fn(async () => makeTypes());
    render(<WorkstationLauncher deps={{ fetchTypes }} />);
    await waitFor(() => screen.getByTestId('workstation-type-monaco'));
    fireEvent.click(screen.getByTestId('workstation-type-monaco'));
    // monaco component isn't built yet -> placeholder, not a crash.
    expect(screen.getByTestId('workstation-unavailable')).toBeTruthy();
    expect(screen.queryByTestId('fake-monaco')).toBeNull();
  });

  it('opens a native type via its registered OSS component', async () => {
    const fetchTypes = vi.fn(async () => makeTypes());
    render(
      <WorkstationLauncher deps={{ fetchTypes, nativeComponents: { monaco: FakeMonaco } }} />,
    );
    await waitFor(() => screen.getByTestId('workstation-type-monaco'));
    fireEvent.click(screen.getByTestId('workstation-type-monaco'));
    expect(screen.getByTestId('fake-monaco').textContent).toBe('monaco:monaco');
    expect(screen.queryByTestId('workstation-unavailable')).toBeNull();
  });

  it('renders an iframe type through the sandboxed frame (external)', async () => {
    const fetchTypes = vi.fn(async () => makeTypes());
    render(<WorkstationLauncher deps={{ fetchTypes, IframeFrame: FakeIframeFrame }} />);
    await waitFor(() => screen.getByTestId('workstation-type-immersive-demo'));
    fireEvent.click(screen.getByTestId('workstation-type-immersive-demo'));
    expect(screen.getByTestId('workstation-iframe')).toBeTruthy();
    expect(screen.getByTestId('fake-mcp-frame')).toBeTruthy();
    // Reuses McpAppFrame's contract: resourceUri = type id, external = true.
    expect(iframeProps).toHaveLength(1);
    expect(iframeProps[0]).toMatchObject({ resourceUri: 'immersive-demo', toolName: 'immersive-demo', external: true });
  });

  it('honest-degrades to an empty catalog on fetch error', async () => {
    const fetchTypes = vi.fn(async () => {
      throw new Error('network down');
    });
    render(<WorkstationLauncher deps={{ fetchTypes }} />);
    await waitFor(() => screen.getByTestId('workstation-empty'));
    expect(screen.getByTestId('workstation-launcher')).toBeTruthy();
  });

  it('uses no emoji (HXI #3)', async () => {
    const fetchTypes = vi.fn(async () => makeTypes());
    const { container } = render(
      <WorkstationLauncher deps={{ fetchTypes, IframeFrame: FakeIframeFrame }} />,
    );
    await waitFor(() => screen.getByTestId('workstation-type-monaco'));
    fireEvent.click(screen.getByTestId('workstation-type-immersive-demo'));
    expect(EMOJI.test(container.textContent ?? '')).toBe(false);
  });
});
