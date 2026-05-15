// AD-722b-4: Vitest coverage for the fleet telemetry hook.
// 3 tests: dispatches frames by agent_id, drops frames missing agent_id,
// closes WebSocket on unmount.
import { renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  type FleetTelemetryFrame,
  useFleetAvatarTelemetry,
} from "../avatars/useFleetAvatarTelemetry";

class MockWebSocket {
  public static instances: MockWebSocket[] = [];
  public onmessage: ((ev: { data: string }) => void) | null = null;
  public onerror: ((ev: unknown) => void) | null = null;
  public closed = false;

  constructor(public readonly url: string) {
    MockWebSocket.instances.push(this);
  }

  close(): void {
    this.closed = true;
  }

  emit(payload: unknown): void {
    this.onmessage?.({ data: JSON.stringify(payload) });
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
});
