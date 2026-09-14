// AD-722b-4: Vitest coverage for the fleet telemetry hook.
// 4 tests: dispatches frames by agent_id, drops frames missing agent_id,
// closes WebSocket on unmount, preserves connection across callback rerenders.
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  type FleetTelemetryFrame,
  useFleetAvatarTelemetry,
} from "../avatars/useFleetAvatarTelemetry";

class MockWebSocket {
  public static instances: MockWebSocket[] = [];
  public onmessage: ((ev: { data: string }) => void) | null = null;
  public onerror: ((ev: unknown) => void) | null = null;
  public onclose: (() => void) | null = null;
  public closed = false;
  public disconnects = 0;

  constructor(public readonly url: string) {
    MockWebSocket.instances.push(this);
  }

  close(): void {
    this.closed = true;
  }

  emit(payload: unknown): void {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }

  disconnect(): void {
    this.closed = true;
    this.disconnects += 1;
    this.onclose?.();
  }
}

const originalWebSocket = globalThis.WebSocket;

describe("useFleetAvatarTelemetry", () => {
  beforeEach(() => {
    MockWebSocket.instances = [];
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (globalThis as any).WebSocket = MockWebSocket;
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.restoreAllMocks();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (globalThis as any).WebSocket = originalWebSocket;
  });

  it("dispatches frames by agent_id", () => {
    const seen: FleetTelemetryFrame[] = [];
    const onFrame = (f: FleetTelemetryFrame) => seen.push(f);
    renderHook(() =>
      useFleetAvatarTelemetry({ onFrame, url: "ws://test/fleet" }),
    );
    const ws = MockWebSocket.instances[0]!;
    ws.emit({ type: "snapshot", agent_id: "ezri", working_state: "idle" });
    ws.emit({ type: "diff", agent_id: "worf", changed: { trust_delta: 0.1 } });
    ws.emit({ type: "ping", agent_id: "data", timestamp: 1 });
    expect(seen).toHaveLength(3);
    expect(seen.map((f) => f.agent_id)).toEqual(["ezri", "worf", "data"]);
  });

  it("drops frames missing agent_id", () => {
    const seen: FleetTelemetryFrame[] = [];
    renderHook(() =>
      useFleetAvatarTelemetry({
        onFrame: (f) => seen.push(f),
        url: "ws://test/fleet",
      }),
    );
    const ws = MockWebSocket.instances[0]!;
    ws.emit({ type: "snapshot", working_state: "idle" });
    expect(seen).toHaveLength(0);
  });

  it("preserves the socket and dispatches only to the latest callback after rerender", () => {
    const firstHandler = vi.fn<(frame: FleetTelemetryFrame) => void>();
    const latestHandler = vi.fn<(frame: FleetTelemetryFrame) => void>();
    const { rerender, unmount } = renderHook(
      ({ onFrame }) =>
        useFleetAvatarTelemetry({
          onFrame,
          enabled: true,
          url: "ws://test/fleet",
        }),
      { initialProps: { onFrame: firstHandler } },
    );

    try {
      expect(firstHandler).not.toBe(latestHandler);
      expect(MockWebSocket.instances).toHaveLength(1);
      const socket = MockWebSocket.instances[0]!;
      const closeSpy = vi.spyOn(socket, "close");
      expect(socket.closed).toBe(false);
      socket.emit({ type: "snapshot", agent_id: "ezri", working_state: "idle" });
      expect(firstHandler).toHaveBeenCalledExactlyOnceWith({
        type: "snapshot",
        agent_id: "ezri",
        payload: { working_state: "idle" },
      });
      expect(latestHandler).not.toHaveBeenCalled();

      rerender({ onFrame: latestHandler });

      expect(MockWebSocket.instances).toHaveLength(1);
      expect(MockWebSocket.instances[0]).toBe(socket);
      expect(closeSpy).not.toHaveBeenCalled();
      expect(socket.closed).toBe(false);
      socket.emit({ type: "diff", agent_id: "worf", changed: { trust_delta: 0.1 } });
      expect(firstHandler).toHaveBeenCalledTimes(1);
      expect(latestHandler).toHaveBeenCalledExactlyOnceWith({
        type: "diff",
        agent_id: "worf",
        payload: { changed: { trust_delta: 0.1 } },
      });
    } finally {
      unmount();
    }
  });

  it("closes WebSocket on unmount", () => {
    const { unmount } = renderHook(() =>
      useFleetAvatarTelemetry({
        onFrame: vi.fn(),
        url: "ws://test/fleet",
      }),
    );
    const ws = MockWebSocket.instances[0]!;
    expect(ws.closed).toBe(false);
    unmount();
    expect(ws.closed).toBe(true);
  });

  it("keeps one connection across repeated progress rerenders", () => {
    const received: number[] = [];
    const { rerender } = renderHook(
      ({ progress }) => useFleetAvatarTelemetry({
        onFrame: () => received.push(progress), url: "ws://test/fleet",
      }),
      { initialProps: { progress: 0 } },
    );
    const socket = MockWebSocket.instances[0]!;
    socket.emit({ type: "ping", agent_id: "ezri" });
    expect(received).toEqual([0]);
    for (let progress = 1; progress <= 120; progress += 1) {
      rerender({ progress });
    }
    expect(MockWebSocket.instances).toHaveLength(1);
    expect(socket.closed).toBe(false);
    socket.emit({ type: "ping", agent_id: "ezri" });
    expect(received).toEqual([0, 120]);
  });

  it("connects only while enabled and ignores the disabled generation", () => {
    const onFrame = vi.fn();
    const { rerender } = renderHook(
      ({ enabled }) => useFleetAvatarTelemetry({ onFrame, enabled, url: "ws://test/fleet" }),
      { initialProps: { enabled: false } },
    );
    expect(MockWebSocket.instances).toHaveLength(0);
    rerender({ enabled: true });
    expect(MockWebSocket.instances).toHaveLength(1);
    const socket = MockWebSocket.instances[0]!;
    const lateMessage = socket.onmessage!;
    socket.emit({ type: "ping", agent_id: "ezri" });
    expect(onFrame).toHaveBeenCalledTimes(1);
    rerender({ enabled: false });
    expect(socket.closed).toBe(true);
    expect(socket.onmessage).toBeNull();
    lateMessage({ data: JSON.stringify({ type: "ping", agent_id: "ezri" }) });
    expect(onFrame).toHaveBeenCalledTimes(1);
    rerender({ enabled: true });
    expect(MockWebSocket.instances).toHaveLength(2);
    MockWebSocket.instances[1]!.emit({ type: "ping", agent_id: "worf" });
    expect(onFrame).toHaveBeenCalledTimes(2);
  });

  it("replaces only the URL-owned connection and fences its late callback", () => {
    const onFrame = vi.fn();
    const { rerender } = renderHook(
      ({ url }) => useFleetAvatarTelemetry({ onFrame, url }),
      { initialProps: { url: "ws://test/first" } },
    );
    const first = MockWebSocket.instances[0]!;
    const lateMessage = first.onmessage!;
    first.emit({ type: "ping", agent_id: "ezri" });
    expect(onFrame).toHaveBeenCalledTimes(1);
    rerender({ url: "ws://test/second" });
    expect(first.closed).toBe(true);
    expect(MockWebSocket.instances).toHaveLength(2);
    expect(MockWebSocket.instances[1]!.url).toBe("ws://test/second");
    lateMessage({ data: JSON.stringify({ type: "ping", agent_id: "ezri" }) });
    expect(onFrame).toHaveBeenCalledTimes(1);
    MockWebSocket.instances[1]!.emit({ type: "ping", agent_id: "worf" });
    expect(onFrame).toHaveBeenCalledTimes(2);
  });

  it("derives the default fleet endpoint from the current page origin", () => {
    renderHook(() => useFleetAvatarTelemetry({ onFrame: vi.fn() }));
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    expect(MockWebSocket.instances).toHaveLength(1);
    expect(MockWebSocket.instances[0]!.url)
      .toBe(`${protocol}//${window.location.host}/api/agent/avatar-telemetry/stream`);
  });

  it("drops invalid JSON and missing or non-string frame identity", () => {
    const onFrame = vi.fn();
    renderHook(() => useFleetAvatarTelemetry({ onFrame, url: "ws://test/fleet" }));
    const socket = MockWebSocket.instances[0]!;
    socket.emit({ type: "ping", agent_id: "ezri" });
    expect(onFrame).toHaveBeenCalledTimes(1);
    socket.onmessage!({ data: "{" });
    for (const payload of [null, {}, [], { type: 1, agent_id: "ezri" }, { type: "ping", agent_id: 1 }]) {
      socket.emit(payload);
    }
    expect(onFrame).toHaveBeenCalledTimes(1);
  });

  it("does not dispatch after unmount or into a remounted consumer", () => {
    const firstHandler = vi.fn();
    const firstMount = renderHook(() =>
      useFleetAvatarTelemetry({ onFrame: firstHandler, url: "ws://test/fleet" }));
    const first = MockWebSocket.instances[0]!;
    const lateMessage = first.onmessage!;
    first.emit({ type: "ping", agent_id: "ezri" });
    expect(firstHandler).toHaveBeenCalledTimes(1);
    firstMount.unmount();
    const latestHandler = vi.fn();
    renderHook(() => useFleetAvatarTelemetry({ onFrame: latestHandler, url: "ws://test/fleet" }));
    lateMessage({ data: JSON.stringify({ type: "ping", agent_id: "ezri" }) });
    expect(firstHandler).toHaveBeenCalledTimes(1);
    expect(latestHandler).not.toHaveBeenCalled();
    MockWebSocket.instances[1]!.emit({ type: "ping", agent_id: "worf" });
    expect(latestHandler).toHaveBeenCalledTimes(1);
  });

  it("keeps at most one active socket through StrictMode setup and cleanup", () => {
    const { unmount } = renderHook(
      () => useFleetAvatarTelemetry({ onFrame: vi.fn(), url: "ws://test/fleet" }),
      { reactStrictMode: true },
    );
    expect(MockWebSocket.instances).toHaveLength(2);
    expect(MockWebSocket.instances.filter(socket => !socket.closed)).toHaveLength(1);
    expect(MockWebSocket.instances[0]!.onmessage).toBeNull();
    unmount();
    expect(MockWebSocket.instances.every(socket => socket.closed)).toBe(true);
  });

  it("invalidates the connection even when closing throws", () => {
    const onFrame = vi.fn();
    const { unmount } = renderHook(() => useFleetAvatarTelemetry({ onFrame, url: "ws://test/fleet" }));
    const socket = MockWebSocket.instances[0]!;
    const lateMessage = socket.onmessage!;
    vi.spyOn(socket, "close").mockImplementation(() => { throw new Error("already closed"); });
    expect(() => unmount()).not.toThrow();
    expect(socket.onmessage).toBeNull();
    lateMessage({ data: JSON.stringify({ type: "ping", agent_id: "ezri" }) });
    expect(onFrame).not.toHaveBeenCalled();
  });

  it("recovers after a server-close event on a successfully streaming connection", () => {
    vi.useFakeTimers();
    const onFrame = vi.fn();
    renderHook(() => useFleetAvatarTelemetry({ onFrame, url: "ws://test/fleet" }));
    const socket = MockWebSocket.instances[0]!;
    socket.emit({ type: "snapshot", agent_id: "ezri", working_state: "idle" });
    expect(onFrame).toHaveBeenCalledTimes(1);
    socket.disconnect();
    expect(socket.disconnects).toBe(1);
    expect(socket.closed).toBe(true);
    act(() => vi.advanceTimersByTime(250));
    expect(MockWebSocket.instances).toHaveLength(2);
    expect(MockWebSocket.instances.filter(candidate => !candidate.closed)).toHaveLength(1);
    MockWebSocket.instances[1]!.emit({ type: "diff", agent_id: "ezri", working_state: "thinking" });
    expect(onFrame).toHaveBeenCalledTimes(2);
  });

  it("exhausts exactly three retries without valid frames and only explicit identity change restarts", () => {
    vi.useFakeTimers();
    const onFrame = vi.fn();
    const { rerender } = renderHook(
      ({ enabled, handler }) => useFleetAvatarTelemetry({ enabled, onFrame: handler, url: "ws://test/fleet" }),
      { initialProps: { enabled: true, handler: onFrame } },
    );
    expect(MockWebSocket.instances).toHaveLength(1);
    for (const [index, delay] of [250, 500, 1000].entries()) {
      const socket = MockWebSocket.instances[index]!;
      const duplicateClose = socket.onclose!;
      socket.onmessage!({ data: "{" });
      socket.emit({ type: "snapshot" });
      socket.disconnect();
      duplicateClose();
      expect(vi.getTimerCount()).toBe(1);
      act(() => vi.advanceTimersByTime(delay - 1));
      expect(MockWebSocket.instances).toHaveLength(index + 1);
      act(() => vi.advanceTimersByTime(1));
      expect(MockWebSocket.instances).toHaveLength(index + 2);
      expect(MockWebSocket.instances.filter(candidate => !candidate.closed)).toHaveLength(1);
    }
    MockWebSocket.instances[3]!.disconnect();
    expect(vi.getTimerCount()).toBe(0);
    act(() => vi.advanceTimersByTime(60_000));
    expect(MockWebSocket.instances).toHaveLength(4);
    expect(onFrame).not.toHaveBeenCalled();
    const latestHandler = vi.fn();
    rerender({ enabled: true, handler: latestHandler });
    expect(MockWebSocket.instances).toHaveLength(4);
    rerender({ enabled: false, handler: latestHandler });
    rerender({ enabled: true, handler: latestHandler });
    expect(MockWebSocket.instances).toHaveLength(5);
    MockWebSocket.instances[4]!.emit({ type: "snapshot", agent_id: "ezri" });
    expect(latestHandler).toHaveBeenCalledTimes(1);
  });

  it("resets the retry episode only after a valid received frame", () => {
    vi.useFakeTimers();
    const onFrame = vi.fn();
    renderHook(() => useFleetAvatarTelemetry({ onFrame, url: "ws://test/fleet" }));
    MockWebSocket.instances[0]!.disconnect();
    act(() => vi.advanceTimersByTime(250));
    expect(MockWebSocket.instances).toHaveLength(2);
    MockWebSocket.instances[1]!.disconnect();
    act(() => vi.advanceTimersByTime(500));
    expect(MockWebSocket.instances).toHaveLength(3);
    const recovered = MockWebSocket.instances[2]!;
    recovered.emit({ type: "snapshot", agent_id: "ezri" });
    expect(onFrame).toHaveBeenCalledTimes(1);
    recovered.disconnect();
    act(() => vi.advanceTimersByTime(249));
    expect(MockWebSocket.instances).toHaveLength(3);
    act(() => vi.advanceTimersByTime(1));
    expect(MockWebSocket.instances).toHaveLength(4);
  });

  it.each(["unmount", "disable", "url"] as const)("cancels pending retries on %s and ignores retired close events", transition => {
    vi.useFakeTimers();
    const onFrame = vi.fn();
    const { rerender, unmount } = renderHook(
      ({ enabled, url }) => useFleetAvatarTelemetry({ onFrame, enabled, url }),
      { initialProps: { enabled: true, url: "ws://test/first" } },
    );
    const old = MockWebSocket.instances[0]!;
    const lateClose = old.onclose!;
    const lateMessage = old.onmessage!;
    old.disconnect();
    expect(old.disconnects).toBe(1);
    expect(vi.getTimerCount()).toBe(1);
    if (transition === "unmount") unmount();
    else if (transition === "disable") rerender({ enabled: false, url: "ws://test/first" });
    else rerender({ enabled: true, url: "ws://test/second" });
    expect(vi.getTimerCount()).toBe(0);
    lateClose();
    lateMessage({ data: JSON.stringify({ type: "ping", agent_id: "ezri" }) });
    act(() => vi.advanceTimersByTime(2000));
    expect(MockWebSocket.instances).toHaveLength(transition === "url" ? 2 : 1);
    expect(onFrame).not.toHaveBeenCalled();
    if (transition === "url") {
      expect(MockWebSocket.instances[1]!.url).toBe("ws://test/second");
      MockWebSocket.instances[1]!.emit({ type: "snapshot", agent_id: "worf" });
      expect(onFrame).toHaveBeenCalledTimes(1);
    }
  });

  it("ignores an already captured retry timer after unmount", () => {
    vi.useFakeTimers();
    const schedule = vi.spyOn(globalThis, "setTimeout");
    const { unmount } = renderHook(() =>
      useFleetAvatarTelemetry({ onFrame: vi.fn(), url: "ws://test/fleet" }));
    MockWebSocket.instances[0]!.disconnect();
    const scheduled = schedule.mock.calls.find(([, delay]) => delay === 250);
    expect(scheduled).toBeDefined();
    const callback = scheduled![0];
    expect(typeof callback).toBe("function");
    unmount();
    expect(vi.getTimerCount()).toBe(0);
    if (typeof callback === "function") callback();
    expect(MockWebSocket.instances).toHaveLength(1);
  });

  it("waits for close rather than retrying concurrently on error", () => {
    vi.useFakeTimers();
    renderHook(() => useFleetAvatarTelemetry({ onFrame: vi.fn(), url: "ws://test/fleet" }));
    const socket = MockWebSocket.instances[0]!;
    expect(socket.onerror).not.toBeNull();
    socket.onerror!({ type: "error" });
    socket.onerror!({ type: "error" });
    expect(vi.getTimerCount()).toBe(0);
    expect(MockWebSocket.instances).toHaveLength(1);
    socket.disconnect();
    expect(vi.getTimerCount()).toBe(1);
  });
});
