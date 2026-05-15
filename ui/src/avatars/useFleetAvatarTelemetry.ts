// AD-722b-4: fleet-level avatar telemetry stream hook.
// v1 surface — subscribes once, dispatches frames by agent_id via callback.
// Per-agent hooks at /api/agent/{id}/avatar-telemetry-stream remain
// functional; this hook does NOT replace them yet (AD-722b-4a forward marker).
import { useEffect, useRef } from "react";

export interface FleetTelemetryFrame {
  type: "snapshot" | "diff" | "ping" | "error";
  agent_id: string;
  payload: Record<string, unknown>;
}

export interface UseFleetAvatarTelemetryOptions {
  onFrame: (frame: FleetTelemetryFrame) => void;
  enabled?: boolean;
  url?: string;
}

export function useFleetAvatarTelemetry({
  onFrame,
  enabled = true,
  url,
}: UseFleetAvatarTelemetryOptions): void {
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!enabled) return;
    const wsUrl = url ?? deriveFleetUrl();
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data as string);
        if (typeof data?.agent_id !== "string" || typeof data?.type !== "string") {
          // Frames without agent_id are out-of-contract for the fleet endpoint.
          return;
        }
        const { agent_id, type, ...payload } = data;
        onFrame({ type, agent_id, payload });
      } catch {
        // Malformed JSON — drop silently; the per-agent endpoint guarantees
        // the contract, the fleet endpoint only adds a fan-out wrapper.
      }
    };

    ws.onerror = () => {
      // Tier-2 silent — caller's onFrame contract is "best-effort."
    };

    return () => {
      try {
        ws.close();
      } catch {
        // ignore
      }
      wsRef.current = null;
    };
  }, [enabled, url, onFrame]);
}

function deriveFleetUrl(): string {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  // AD-722b-4 (revised pass-2 2026-05-14): full path resolves under the
  // ``agents`` router prefix ``/api/agent`` (src/probos/routers/agents.py:30).
  return `${proto}//${window.location.host}/api/agent/avatar-telemetry/stream`;
}
