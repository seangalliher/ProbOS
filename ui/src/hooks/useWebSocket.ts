/* WebSocket connection hook with reconnection (AD-255) */

import { useEffect, useRef } from 'react';
import { useStore } from '../store/useStore';
import type { WSEvent } from '../store/types';

const MAX_BACKOFF = 30_000;

export function buildEventWebSocketUrl(location: Location = window.location): string {
  const base = `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/ws/events`;
  const token = new URLSearchParams(location.search).get('token');
  return token ? `${base}?token=${encodeURIComponent(token)}` : base;
}

export function useWebSocket() {
  const handleEvent = useStore((s) => s.handleEvent);
  const setConnected = useStore((s) => s.setConnected);
  const wsRef = useRef<WebSocket | null>(null);
  const backoffRef = useRef(1000);
  const mountedRef = useRef(true);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    mountedRef.current = true;

    function connect() {
      if (!mountedRef.current) return;

      const socket = new WebSocket(buildEventWebSocketUrl());
      wsRef.current = socket;

      socket.onopen = () => {
        if (wsRef.current !== socket) return;
        backoffRef.current = 1000;
        setConnected(true);
      };

      socket.onmessage = (ev) => {
        if (wsRef.current !== socket) return;
        try {
          const event = JSON.parse(ev.data);
          if (event.type === 'ping') return;
          handleEvent(event as WSEvent);
        } catch {
          // ignore malformed messages
        }
      };

      socket.onclose = () => {
        if (wsRef.current !== socket) return;
        wsRef.current = null;
        setConnected(false);
        useStore.setState({ liveGeneration: null });
        if (!mountedRef.current) return;
        const delay = backoffRef.current;
        backoffRef.current = Math.min(delay * 2, MAX_BACKOFF);
        if (reconnectTimeoutRef.current !== null) {
          clearTimeout(reconnectTimeoutRef.current);
        }
        reconnectTimeoutRef.current = setTimeout(() => {
          reconnectTimeoutRef.current = null;
          connect();
        }, delay);
      };

      socket.onerror = () => {
        if (wsRef.current === socket) socket.close();
      };
    }

    connect();

    return () => {
      mountedRef.current = false;
      if (reconnectTimeoutRef.current !== null) {
        clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [handleEvent, setConnected]);
}
