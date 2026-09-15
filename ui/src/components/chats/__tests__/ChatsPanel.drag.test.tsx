// AD-940: tests for the draggable CHATS panel. Mocks the threadApi list/
// participant wrappers (the panel's on-open fetch honest-degrades to []) and
// seeds the REAL store (BF-287) — chatsOpen + chatsPanelPos. Covers the store
// action, the panel rendering at the store position, the header drag affordance
// (cursor:move + a mousedown->move->up sequence updating chatsPanelPos), and
// the HXI no-emoji guard.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { useStore } from '../../../store/useStore';

vi.mock('../../sidebar/threadApi', () => ({
  listThreads: vi.fn(),
  addParticipant: vi.fn(),
  getThread: vi.fn(),
  repairRoomSummaries: vi.fn().mockResolvedValue({ kind: 'success', summaries: {} }),
  createThread: vi.fn(),
}));

import { listThreads } from '../../sidebar/threadApi';
import ChatsPanel from '../ChatsPanel';

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal('innerWidth', 1440);
  vi.stubGlobal('innerHeight', 1000);
});

async function renderOpen(pos: { x: number; y: number } = { x: 60, y: 60 }) {
  vi.mocked(listThreads).mockResolvedValue([]);
  useStore.setState({ agents: new Map(), chatsOpen: true, chatsPanelPos: pos });
  const r = render(<ChatsPanel />);
  // Flush the on-open fetch (empty list -> empty state) to settle async setState.
  await screen.findByTestId('chats-empty');
  return r;
}

afterEach(() => {
  cleanup();
  useStore.setState({ agents: new Map(), chatsOpen: false, chatsPanelPos: { x: 60, y: 60 } });
  vi.clearAllMocks();
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe('AD-940 draggable CHATS panel', () => {
  it('setChatsPanelPos updates chatsPanelPos', () => {
    useStore.getState().setChatsPanelPos({ x: 240, y: 360 });
    expect(useStore.getState().chatsPanelPos).toEqual({ x: 240, y: 360 });
  });

  it('renders the panel root at left/top from chatsPanelPos', async () => {
    await renderOpen({ x: 128, y: 200 });
    const panel = screen.getByTestId('chats-panel') as HTMLElement;
    expect(panel.style.left).toBe('128px');
    expect(panel.style.top).toBe('200px');
  });

  it('header is a move-cursor drag handle; mousedown->move->up moves the panel', async () => {
    await renderOpen({ x: 60, y: 60 });
    const handle = screen.getByTestId('chats-drag-handle') as HTMLElement;
    expect(handle.style.cursor).toBe('move');

    fireEvent.mouseDown(handle, { clientX: 100, clientY: 100 });
    fireEvent.mouseMove(window, { clientX: 130, clientY: 150 });
    fireEvent.mouseUp(window);

    // origin {60,60} + delta {30,50} = {90,110}.
    expect(useStore.getState().chatsPanelPos).toEqual({ x: 90, y: 110 });
  });

  it('the New-chat / Close controls do not start a drag (mousedown stopPropagation)', async () => {
    await renderOpen({ x: 60, y: 60 });
    const newChat = screen.getByTestId('new-chat-button');
    const close = screen.getByTestId('chats-close');
    // A mousedown that reaches a control then a drag move must NOT relocate the
    // panel (the control stops propagation, so the header handler never armed).
    fireEvent.mouseDown(newChat, { clientX: 200, clientY: 200 });
    fireEvent.mouseMove(window, { clientX: 260, clientY: 260 });
    fireEvent.mouseUp(window);
    expect(useStore.getState().chatsPanelPos).toEqual({ x: 60, y: 60 });

    fireEvent.mouseDown(close, { clientX: 200, clientY: 200 });
    fireEvent.mouseMove(window, { clientX: 280, clientY: 280 });
    fireEvent.mouseUp(window);
    expect(useStore.getState().chatsPanelPos).toEqual({ x: 60, y: 60 });
  });

  it('clamps oversized offscreen preferences without losing their desktop values', async () => {
    const savedSize = { w: 800, h: 800 };
    const savedPos = { x: 1000, y: 300 };
    localStorage.setItem('probos.chatsPanel.size', JSON.stringify(savedSize));
    vi.stubGlobal('innerWidth', 390);
    vi.stubGlobal('innerHeight', 844);
    await renderOpen(savedPos);
    const panel = screen.getByTestId('chats-panel');
    expect(panel).toHaveStyle({ left: '8px', top: '36px', width: '374px', height: '800px' });
    expect(JSON.parse(localStorage.getItem('probos.chatsPanel.size')!)).toEqual(savedSize);
    expect(useStore.getState().chatsPanelPos).toEqual(savedPos);
    vi.stubGlobal('innerWidth', 1920);
    vi.stubGlobal('innerHeight', 1200);
    fireEvent(window, new Event('resize'));
    expect(panel).toHaveStyle({ left: '1000px', top: '300px', width: '800px', height: '800px' });
    expect(JSON.parse(localStorage.getItem('probos.chatsPanel.size')!)).toEqual(savedSize);
    expect(useStore.getState().chatsPanelPos).toEqual(savedPos);
  });

  it.each(['null', '{}', '{"w":-1,"h":600}', '{"w":440,"h":1}', '{"w":1e999,"h":600}'])('rejects invalid saved dimensions %s', async (saved) => {
    localStorage.setItem('probos.chatsPanel.size', saved);
    await renderOpen({ x: Number.NaN, y: Number.POSITIVE_INFINITY });
    expect(screen.getByTestId('chats-panel')).toHaveStyle({ width: '440px', height: '600px', left: '60px', top: '60px' });
    expect(JSON.parse(localStorage.getItem('probos.chatsPanel.size')!)).toEqual({ w: 440, h: 600 });
  });

  it('starts dragging from visible geometry and bounds the result', async () => {
    vi.stubGlobal('innerWidth', 390);
    vi.stubGlobal('innerHeight', 500);
    await renderOpen({ x: 9000, y: -100 });
    const panel = screen.getByTestId('chats-panel');
    expect(panel).toHaveStyle({ left: '8px', top: '8px', width: '374px', height: '484px' });
    fireEvent.mouseDown(screen.getByTestId('chats-drag-handle'), { clientX: 20, clientY: 20 });
    fireEvent.mouseMove(window, { clientX: 1000, clientY: -1000 });
    fireEvent.mouseUp(window);
    expect(useStore.getState().chatsPanelPos).toEqual({ x: 8, y: 8 });
    expect(panel).toHaveStyle({ left: '8px', top: '8px' });
  });

  it('no-emoji guard', async () => {
    const { container } = await renderOpen();
    expect(container.innerHTML).not.toMatch(/\p{Extended_Pictographic}/u);
  });
});
