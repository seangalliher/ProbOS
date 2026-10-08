/** BF-888 (#1367): the profile panel names its chat composer, so the avatar popout it opens is placed clear
 *  of the message input, Send and voice. Crosses the seam: panel -> ProfileChatTab's composer row -> popout. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, within } from '@testing-library/react';

vi.mock('@react-three/fiber', () => ({
  useFrame: () => {},
  Canvas: ({ children }: any) => <div data-testid="canvas">{children}</div>,
}));
vi.mock('@react-three/drei', () => ({ OrbitControls: () => null }));
vi.mock('../components/profile/CrewVRM', () => ({
  CrewVRM: () => <div data-testid="crew-vrm" />,
  applyRestingExpressionMultiMesh: () => 0,
}));
vi.mock('../components/profile/ParametricAvatar', () => ({
  ParametricAvatar: () => <div data-testid="parametric-avatar" />,
}));
vi.mock('../audio/voice', () => ({
  flushSpeechQueue: vi.fn(),
  getServerPiperVoices: vi.fn(async () => null),
  getAvailableVoices: vi.fn(() => []),
  onSpeechEvent: () => () => {},
  speakResponse: vi.fn(),
  stripMarkdownForSpeech: (s: string) => s,
}));
vi.mock('../audio/speechInput', () => ({
  isSpeechRecognitionSupported: () => true,
  startListening: vi.fn(),
  stopListening: vi.fn(),
}));

import { AgentProfilePanel } from '../components/profile/AgentProfilePanel';
import { useStore } from '../store/useStore';

const AGENT_ID = 'agent-counselor';

let originalState: ReturnType<typeof useStore.getState>;
let originalWidth: PropertyDescriptor | undefined;
let originalHeight: PropertyDescriptor | undefined;
let originalSize: string | null;

function setViewport(width: number, height: number): void {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: width });
  Object.defineProperty(window, 'innerHeight', { configurable: true, value: height });
}

function restoreViewport(name: 'innerWidth' | 'innerHeight', original: PropertyDescriptor | undefined): void {
  if (original) Object.defineProperty(window, name, original);
  else delete (window as unknown as Record<string, unknown>)[name];
}

function rect(left: number, top: number, width: number, height: number): DOMRect {
  return {
    x: left, y: top, left, top, width, height, right: left + width, bottom: top + height, toJSON: () => ({}),
  } as DOMRect;
}

function geometry(dialog: HTMLElement): { x: number; y: number; w: number; h: number } {
  return {
    x: Number.parseFloat(dialog.style.left),
    y: Number.parseFloat(dialog.style.top),
    w: Number.parseFloat(dialog.style.width),
    h: Number.parseFloat(dialog.style.height),
  };
}

/** Render the panel's chat tab, prove the named composer row holds the controls, and give it a measured rect. */
function renderWithComposerAt(composerRect: DOMRect): void {
  render(<AgentProfilePanel />);
  const composer = screen.getByTestId('profile-chat-composer');
  within(composer).getByPlaceholderText('Message...');
  within(composer).getByRole('button', { name: 'Send' });
  within(composer).getByRole('button', { name: 'Voice input' });
  vi.spyOn(composer, 'getBoundingClientRect').mockReturnValue(composerRect);
}

beforeEach(() => {
  originalState = useStore.getState();
  originalWidth = Object.getOwnPropertyDescriptor(window, 'innerWidth');
  originalHeight = Object.getOwnPropertyDescriptor(window, 'innerHeight');
  originalSize = localStorage.getItem('hxi_profile_panel_size');
  localStorage.removeItem('hxi_profile_panel_size');
  if (!(Element.prototype as any).scrollIntoView) {
    (Element.prototype as any).scrollIntoView = vi.fn();
  }
  useStore.setState({
    activeProfileAgent: AGENT_ID,
    activeProfileThreadId: null,
    agents: new Map([[AGENT_ID, {
      id: AGENT_ID, agent_type: 'counselor', callsign: 'Troi', displayName: 'Troi', pool: 'medical',
      state: 'idle', tier: 'domain', capabilities: [], confidence: 0.7, trust: 0.7, isCrew: true,
    } as any]]),
    profilePanelPos: { x: 100, y: 100 },
    poolToGroup: { medical: 'medical' },
    agentConversations: new Map(),
  });
  vi.stubGlobal('fetch', vi.fn((url: unknown) => {
    const body = String(url) === '/api/config/avatars-enabled' ? { enabled: true } : {};
    return Promise.resolve({ ok: true, json: () => Promise.resolve(body) });
  }));
});

afterEach(() => {
  cleanup();
  useStore.setState(originalState, true);
  restoreViewport('innerWidth', originalWidth);
  restoreViewport('innerHeight', originalHeight);
  if (originalSize === null) localStorage.removeItem('hxi_profile_panel_size');
  else localStorage.setItem('hxi_profile_panel_size', originalSize);
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('BF-888 AgentProfilePanel opens the avatar popout clear of its composer', () => {
  it('opens directly above the composer at 430x932, clear of Send and voice', async () => {
    setViewport(430, 932);
    renderWithComposerAt(rect(11, 634, 390, 45));
    fireEvent.click(await screen.findByRole('button', { name: 'Show avatar' }));
    expect(geometry(screen.getByRole('dialog', { name: `Avatar — ${AGENT_ID}` })))
      .toEqual({ x: 86, y: 146, w: 320, h: 480 });
  });

  it('keeps the bottom-right home at 1440x1000, where the composer is clear of it', async () => {
    setViewport(1440, 1000);
    renderWithComposerAt(rect(101, 634, 390, 45));
    fireEvent.click(await screen.findByRole('button', { name: 'Show avatar' }));
    expect(geometry(screen.getByRole('dialog', { name: `Avatar — ${AGENT_ID}` })))
      .toEqual({ x: 1096, y: 496, w: 320, h: 480 });
  });
});

describe('BF-888 A-1 AgentProfilePanel: the avatar opened on another tab', () => {
  it('opened on Work at 430x932, moves clear of the composer once Chat is selected', async () => {
    setViewport(430, 932);
    const measure = Element.prototype.getBoundingClientRect;
    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function (this: Element) {
      return this.getAttribute('data-testid') === 'profile-chat-composer' ? rect(11, 634, 390, 45) : measure.call(this);
    });
    render(<AgentProfilePanel />);
    fireEvent.click(screen.getByRole('button', { name: 'Work' }));
    expect(screen.queryByTestId('profile-chat-composer')).toBeNull();
    fireEvent.click(await screen.findByRole('button', { name: 'Show avatar' }));
    const dialog = screen.getByRole('dialog', { name: `Avatar — ${AGENT_ID}` });
    expect(geometry(dialog)).toEqual({ x: 86, y: 428, w: 320, h: 480 });
    fireEvent.click(screen.getByRole('button', { name: 'Chat' }));
    within(await screen.findByTestId('profile-chat-composer')).getByRole('button', { name: 'Voice input' });
    expect(geometry(dialog)).toEqual({ x: 86, y: 146, w: 320, h: 480 });
  });
});
