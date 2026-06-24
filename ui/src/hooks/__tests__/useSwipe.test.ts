// AD-708d: unit tests for the useSwipe pointer-based horizontal swipe detector.
// The hook uses only refs (no state), so the returned handlers can be called
// directly with plain { clientX, clientY } coord objects — no jsdom pointer
// event synthesis is needed at the hook level (the MobileShell integration test
// covers fireEvent.pointer* driving the real switch).
import { describe, it, expect, vi } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useSwipe } from '../useSwipe';

describe('AD-708d useSwipe', () => {
  it('fires onSwipeLeft once for a left-dominant swipe past the threshold', () => {
    const onSwipeLeft = vi.fn();
    const onSwipeRight = vi.fn();
    const { result } = renderHook(() => useSwipe({ onSwipeLeft, onSwipeRight }));

    result.current.onPointerDown({ clientX: 300, clientY: 100 });
    result.current.onPointerUp({ clientX: 80, clientY: 100 }); // dx = -220

    expect(onSwipeLeft).toHaveBeenCalledTimes(1);
    expect(onSwipeRight).not.toHaveBeenCalled();
  });

  it('fires onSwipeRight once for a right-dominant swipe past the threshold', () => {
    const onSwipeLeft = vi.fn();
    const onSwipeRight = vi.fn();
    const { result } = renderHook(() => useSwipe({ onSwipeLeft, onSwipeRight }));

    result.current.onPointerDown({ clientX: 80, clientY: 100 });
    result.current.onPointerUp({ clientX: 300, clientY: 100 }); // dx = +220

    expect(onSwipeRight).toHaveBeenCalledTimes(1);
    expect(onSwipeLeft).not.toHaveBeenCalled();
  });

  it('does nothing for a horizontal move below the threshold', () => {
    const onSwipeLeft = vi.fn();
    const onSwipeRight = vi.fn();
    const { result } = renderHook(() => useSwipe({ onSwipeLeft, onSwipeRight }));

    result.current.onPointerDown({ clientX: 100, clientY: 100 });
    result.current.onPointerUp({ clientX: 130, clientY: 100 }); // dx = +30 (< 50)

    expect(onSwipeLeft).not.toHaveBeenCalled();
    expect(onSwipeRight).not.toHaveBeenCalled();
  });

  it('ignores a vertical-dominant gesture (scroll guard)', () => {
    const onSwipeLeft = vi.fn();
    const onSwipeRight = vi.fn();
    const { result } = renderHook(() => useSwipe({ onSwipeLeft, onSwipeRight }));

    // dx = +60 (> threshold) but dy = +300, so |dx| < |dy| -> ignored.
    result.current.onPointerDown({ clientX: 100, clientY: 100 });
    result.current.onPointerUp({ clientX: 160, clientY: 400 });

    expect(onSwipeLeft).not.toHaveBeenCalled();
    expect(onSwipeRight).not.toHaveBeenCalled();
  });

  it('does not throw or fire when pointer-up arrives without a prior pointer-down', () => {
    const onSwipeLeft = vi.fn();
    const onSwipeRight = vi.fn();
    const { result } = renderHook(() => useSwipe({ onSwipeLeft, onSwipeRight }));

    expect(() => result.current.onPointerUp({ clientX: 200, clientY: 100 })).not.toThrow();
    expect(onSwipeLeft).not.toHaveBeenCalled();
    expect(onSwipeRight).not.toHaveBeenCalled();
  });

  it('honors a custom threshold', () => {
    const onSwipeLeft = vi.fn();
    const onSwipeRight = vi.fn();
    const { result } = renderHook(() => useSwipe({ onSwipeLeft, onSwipeRight, threshold: 100 }));

    // dx = +60 < custom threshold -> no-op.
    result.current.onPointerDown({ clientX: 100, clientY: 100 });
    result.current.onPointerUp({ clientX: 160, clientY: 100 });
    expect(onSwipeRight).not.toHaveBeenCalled();

    // dx = +120 > custom threshold -> fires.
    result.current.onPointerDown({ clientX: 100, clientY: 100 });
    result.current.onPointerUp({ clientX: 220, clientY: 100 });
    expect(onSwipeRight).toHaveBeenCalledTimes(1);
    expect(onSwipeLeft).not.toHaveBeenCalled();
  });
});
