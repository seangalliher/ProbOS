/** AD-922: MeetingMicButton presentational tests. Pure render — the capture
 *  lifecycle lives in useMeetingMic (tested separately). No emoji (HXI #3). */
import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/react';
import { MeetingMicButton } from '../MeetingMicButton';
import MeetingMicButtonSource from '../MeetingMicButton?raw';

describe('MeetingMicButton', () => {
  it('renders the meeting-mic testid', () => {
    const { getByTestId } = render(
      <MeetingMicButton capturing={false} blocked={false} speaking={false} onToggle={() => {}} />,
    );
    expect(getByTestId('meeting-mic')).toBeTruthy();
  });

  it('fires onToggle on click', () => {
    const onToggle = vi.fn();
    const { getByTestId } = render(
      <MeetingMicButton capturing={false} blocked={false} speaking={false} onToggle={onToggle} />,
    );
    fireEvent.click(getByTestId('meeting-mic'));
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it('aria-pressed reflects capturing', () => {
    const { getByTestId, rerender } = render(
      <MeetingMicButton capturing={false} blocked={false} speaking={false} onToggle={() => {}} />,
    );
    expect(getByTestId('meeting-mic').getAttribute('aria-pressed')).toBe('false');
    rerender(
      <MeetingMicButton capturing blocked={false} speaking={false} onToggle={() => {}} />,
    );
    expect(getByTestId('meeting-mic').getAttribute('aria-pressed')).toBe('true');
  });

  it('is disabled when blocked', () => {
    const { getByTestId } = render(
      <MeetingMicButton capturing={false} blocked speaking={false} onToggle={() => {}} />,
    );
    expect((getByTestId('meeting-mic') as HTMLButtonElement).disabled).toBe(true);
  });

  it('renders the muted treatment when an agent is speaking', () => {
    const { getByTestId } = render(
      <MeetingMicButton capturing={false} blocked={false} speaking onToggle={() => {}} />,
    );
    // Echo-gate visual: opacity is reduced while an agent speaks.
    expect(getByTestId('meeting-mic').style.opacity).toBe('0.5');
  });

  it('has no emoji in the rendered output or source', () => {
    const { container } = render(
      <MeetingMicButton capturing={false} blocked={false} speaking={false} onToggle={() => {}} />,
    );
    expect(container.innerHTML).not.toMatch(/\p{Extended_Pictographic}/u);
    expect(MeetingMicButtonSource).not.toMatch(/\p{Extended_Pictographic}/u);
  });
});
