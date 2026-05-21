/**
 * AD-759 connection state machine for the runtime ↔ renderer link.
 *
 * Tracks whether the renderer is currently connected to the ProbOS runtime
 * at `http://127.0.0.1:8765`. Pure — no Electron dependency — so we can
 * unit-test transitions.
 *
 * States:
 *   - "connecting"  — initial; renderer is loading or retrying.
 *   - "connected"   — renderer `did-finish-load` fired.
 *   - "disconnected"— renderer `did-fail-load` fired or manual disconnect.
 */

import type { ConnectionStatus } from "./trayMenu.js";

export type ConnectionEvent =
  | { type: "load-start" }
  | { type: "load-success" }
  | { type: "load-failure"; errorCode?: number; description?: string }
  | { type: "manual-retry" }
  | { type: "manual-reconnect" };

export interface ConnectionStateMachine {
  readonly state: ConnectionStatus;
  send(event: ConnectionEvent): ConnectionStatus;
  subscribe(listener: (s: ConnectionStatus) => void): () => void;
}

export function createConnectionStateMachine(
  initial: ConnectionStatus = "connecting",
): ConnectionStateMachine {
  let state: ConnectionStatus = initial;
  const listeners = new Set<(s: ConnectionStatus) => void>();

  function transition(next: ConnectionStatus): ConnectionStatus {
    if (next !== state) {
      state = next;
      for (const l of listeners) {
        l(state);
      }
    }
    return state;
  }

  return {
    get state() {
      return state;
    },
    send(event: ConnectionEvent): ConnectionStatus {
      switch (event.type) {
        case "load-start":
          return transition("connecting");
        case "load-success":
          return transition("connected");
        case "load-failure":
          return transition("disconnected");
        case "manual-retry":
        case "manual-reconnect":
          return transition("connecting");
      }
    },
    subscribe(listener: (s: ConnectionStatus) => void): () => void {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
  };
}
