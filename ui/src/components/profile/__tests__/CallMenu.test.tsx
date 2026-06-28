// AD-1058: tests for the Teams-style CallMenu. Presentational — verifies the
// idle Call button + Video/Audio dropdown, the active End-call button, the
// callbacks, the busy-disable, Escape-to-dismiss, and the HXI no-emoji guard.
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { CallMenu } from '../CallMenu';
import callMenuSource from '../CallMenu.tsx?raw';

const EMOJI_RE = /\p{Extended_Pictographic}/u;

const noop = () => {};

afterEach(() => cleanup());

describe('AD-1058 CallMenu', () => {
  it('idle: shows the Call button, no End-call button, dropdown closed', () => {
    render(<CallMenu active={false} onVideoCall={noop} onAudioCall={noop} onEndCall={noop} />);
    expect(screen.getByTestId('call-start')).toBeTruthy();
    expect(screen.queryByTestId('call-end')).toBeNull();
    expect(screen.queryByTestId('call-menu')).toBeNull();
  });

  it('opens the Video/Audio dropdown on click', () => {
    render(<CallMenu active={false} onVideoCall={noop} onAudioCall={noop} onEndCall={noop} />);
    fireEvent.click(screen.getByTestId('call-start'));
    expect(screen.getByTestId('call-menu')).toBeTruthy();
    expect(screen.getByTestId('call-video')).toBeTruthy();
    expect(screen.getByTestId('call-audio')).toBeTruthy();
  });

  it('Video call fires onVideoCall and closes the menu', () => {
    const onVideo = vi.fn();
    render(<CallMenu active={false} onVideoCall={onVideo} onAudioCall={noop} onEndCall={noop} />);
    fireEvent.click(screen.getByTestId('call-start'));
    fireEvent.click(screen.getByTestId('call-video'));
    expect(onVideo).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId('call-menu')).toBeNull();
  });

  it('Audio call fires onAudioCall', () => {
    const onAudio = vi.fn();
    render(<CallMenu active={false} onVideoCall={noop} onAudioCall={onAudio} onEndCall={noop} />);
    fireEvent.click(screen.getByTestId('call-start'));
    fireEvent.click(screen.getByTestId('call-audio'));
    expect(onAudio).toHaveBeenCalledTimes(1);
  });

  it('active: shows End call (not the Call button) and fires onEndCall', () => {
    const onEnd = vi.fn();
    render(<CallMenu active onVideoCall={noop} onAudioCall={noop} onEndCall={onEnd} />);
    expect(screen.queryByTestId('call-start')).toBeNull();
    fireEvent.click(screen.getByTestId('call-end'));
    expect(onEnd).toHaveBeenCalledTimes(1);
  });

  it('busy disables the Call button', () => {
    render(<CallMenu active={false} busy onVideoCall={noop} onAudioCall={noop} onEndCall={noop} />);
    expect((screen.getByTestId('call-start') as HTMLButtonElement).disabled).toBe(true);
  });

  it('Escape closes the dropdown', () => {
    render(<CallMenu active={false} onVideoCall={noop} onAudioCall={noop} onEndCall={noop} />);
    fireEvent.click(screen.getByTestId('call-start'));
    expect(screen.getByTestId('call-menu')).toBeTruthy();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByTestId('call-menu')).toBeNull();
  });

  it('HXI #3: the source carries no emoji', () => {
    expect(callMenuSource).not.toMatch(EMOJI_RE);
  });
});
