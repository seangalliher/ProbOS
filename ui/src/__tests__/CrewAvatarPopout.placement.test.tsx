/** BF-888 (#1367): the detached avatar popout opens clear of the region its owner names. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, within } from '@testing-library/react';

vi.mock('@react-three/fiber', () => ({
  Canvas: ({ children }: any) => <div data-testid="canvas">{children}</div>,
  useFrame: () => {},
}));
vi.mock('@react-three/drei', () => ({ OrbitControls: () => null }));
vi.mock('../components/profile/CrewVRM', () => ({ CrewVRM: () => <div data-testid="crew-vrm" /> }));
vi.mock('../components/profile/ParametricAvatar', () => ({
  ParametricAvatar: () => <div data-testid="parametric-avatar" />,
}));

import { CrewAvatarPopout } from '../components/profile/CrewAvatarPopout';
import type { KeepClearRect } from '../components/profile/avatarPopoutPlacement';
import type { AgentSignals } from '../components/profile/avatarSignals';

const idleSignals: AgentSignals = { trust_delta: 0, load: 0, working_state: 'idle', tier3_alert: false };
// The composer row as Chromium measures it with the panel at its default position.
const NARROW_COMPOSER: KeepClearRect = { left: 11, top: 634, right: 401, bottom: 679 };
const DESKTOP_COMPOSER: KeepClearRect = { left: 101, top: 634, right: 491, bottom: 679 };

let originalWidth: PropertyDescriptor | undefined;
let originalHeight: PropertyDescriptor | undefined;

function setViewport(width: number, height: number): void {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: width });
  Object.defineProperty(window, 'innerHeight', { configurable: true, value: height });
}

function restoreViewport(name: 'innerWidth' | 'innerHeight', original: PropertyDescriptor | undefined): void {
  if (original) Object.defineProperty(window, name, original);
  else delete (window as unknown as Record<string, unknown>)[name];
}

function renderPopout(keepClear?: () => KeepClearRect | null): HTMLElement {
  render(
    <CrewAvatarPopout
      agentId="agent-007"
      appearance={null}
      departmentColor="#d0a030"
      agentSignals={idleSignals}
      onClose={() => {}}
      keepClear={keepClear}
    />,
  );
  return screen.getByRole('dialog', { name: 'Avatar — agent-007' });
}

function geometry(dialog: HTMLElement): { x: number; y: number; w: number; h: number } {
  return {
    x: Number.parseFloat(dialog.style.left),
    y: Number.parseFloat(dialog.style.top),
    w: Number.parseFloat(dialog.style.width),
    h: Number.parseFloat(dialog.style.height),
  };
}

beforeEach(() => {
  originalWidth = Object.getOwnPropertyDescriptor(window, 'innerWidth');
  originalHeight = Object.getOwnPropertyDescriptor(window, 'innerHeight');
});

afterEach(() => {
  cleanup();
  restoreViewport('innerWidth', originalWidth);
  restoreViewport('innerHeight', originalHeight);
});

describe('BF-888 CrewAvatarPopout opening placement', () => {
  it('opens at the bottom-right home at 1440x1000, as before, when the composer is clear of it', () => {
    setViewport(1440, 1000);
    const keepClear = vi.fn(() => DESKTOP_COMPOSER);
    expect(geometry(renderPopout(keepClear))).toEqual({ x: 1096, y: 496, w: 320, h: 480 });
    expect(keepClear).toHaveBeenCalledTimes(1);
  });

  it('opens directly above the composer at 430x932 instead of covering it', () => {
    setViewport(430, 932);
    expect(geometry(renderPopout(() => NARROW_COMPOSER))).toEqual({ x: 86, y: 146, w: 320, h: 480 });
  });

  it('opens at the home when the owner names no region, or the reader finds none', () => {
    setViewport(430, 932);
    expect(geometry(renderPopout())).toEqual({ x: 86, y: 428, w: 320, h: 480 });
    cleanup();
    expect(geometry(renderPopout(() => null))).toEqual({ x: 86, y: 428, w: 320, h: 480 });
  });

  it('reads the region once and never re-places a popout the user drags or resizes', () => {
    setViewport(430, 932);
    const keepClear = vi.fn(() => NARROW_COMPOSER);
    const dialog = renderPopout(keepClear);
    fireEvent.mouseDown(screen.getByText('agent-007'), { clientX: 200, clientY: 160 });
    fireEvent.mouseMove(window, { clientX: 150, clientY: 400 });
    fireEvent.mouseUp(window);
    expect(geometry(dialog)).toEqual({ x: 36, y: 386, w: 320, h: 480 });
    fireEvent.mouseDown(screen.getByLabelText('Resize avatar'), { clientX: 356, clientY: 866 });
    fireEvent.mouseMove(window, { clientX: 376, clientY: 896 });
    fireEvent.mouseUp(window);
    expect(geometry(dialog)).toEqual({ x: 36, y: 386, w: 340, h: 510 });
    expect(keepClear).toHaveBeenCalledTimes(1);
  });
});

describe('BF-888 A-1 a composer that appears after the popout opened', () => {
  // Opens a popout whose owner has no composer yet; `reveal` hands it a new reader that finds `region`.
  function openWithoutComposer(agentId: string): { dialog: HTMLElement; reveal: (region: KeepClearRect) => void } {
    const props = { agentId, appearance: null, departmentColor: '#d0a030', agentSignals: idleSignals, onClose: () => {} };
    const view = render(<CrewAvatarPopout {...props} keepClear={() => null} />);
    return {
      dialog: screen.getByRole('dialog', { name: `Avatar — ${agentId}` }),
      reveal: region => view.rerender(<CrewAvatarPopout {...props} keepClear={() => region} />),
    };
  }

  it('completes the opening placement once, when a new reader first finds the composer (430x932)', () => {
    setViewport(430, 932);
    const late = openWithoutComposer('agent-007');
    expect(geometry(late.dialog)).toEqual({ x: 86, y: 428, w: 320, h: 480 });
    late.reveal(NARROW_COMPOSER);
    expect(geometry(late.dialog)).toEqual({ x: 86, y: 146, w: 320, h: 480 });
    late.reveal({ left: 11, top: 300, right: 401, bottom: 345 });
    expect(geometry(late.dialog)).toEqual({ x: 86, y: 146, w: 320, h: 480 });
  });

  it('never moves a popout the user dragged or resized before the composer appeared', () => {
    setViewport(430, 932);
    const untouched = openWithoutComposer('agent-untouched');
    const dragged = openWithoutComposer('agent-dragged');
    const resized = openWithoutComposer('agent-resized');
    fireEvent.mouseDown(screen.getByText('agent-dragged'), { clientX: 200, clientY: 440 });
    fireEvent.mouseMove(window, { clientX: 150, clientY: 400 });
    fireEvent.mouseUp(window);
    fireEvent.mouseDown(within(resized.dialog).getByLabelText('Resize avatar'), { clientX: 400, clientY: 900 });
    fireEvent.mouseMove(window, { clientX: 380, clientY: 880 });
    fireEvent.mouseUp(window);
    for (const late of [untouched, dragged, resized]) late.reveal(NARROW_COMPOSER);
    expect(geometry(untouched.dialog)).toEqual({ x: 86, y: 146, w: 320, h: 480 });
    expect(geometry(dragged.dialog)).toEqual({ x: 36, y: 388, w: 320, h: 480 });
    expect(geometry(resized.dialog)).toEqual({ x: 86, y: 428, w: 300, h: 460 });
  });
});
