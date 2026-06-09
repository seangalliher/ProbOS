// AD-940: tests for the draggable CHATS panel. Mocks the threadApi list/
// participant wrappers (the panel's on-open fetch honest-degrades to []) and
// seeds the REAL store (BF-287) — chatsOpen + chatsPanelPos. Covers the store
// action, the panel rendering at the store position, the header drag affordance
// (cursor:move + a mousedown->move->up sequence updating chatsPanelPos), and
// the HXI no-emoji guard.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { useStore } from '../../../store/useStore';

vi.mock('../../sidebar/threadApi', () => ({
  listThreads: vi.fn(),
  addParticipant: vi.fn(),
  createThread: vi.fn(),
}));

import { listThreads } from '../../sidebar/threadApi';
import ChatsPanel from '../ChatsPanel';

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

  it('no-emoji guard', async () => {
    const { container } = await renderOpen();
    expect(container.innerHTML).not.toMatch(/\p{Extended_Pictographic}/u);
  });
});
