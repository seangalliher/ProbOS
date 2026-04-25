# Build Prompt: Fix WebSocket Protocol Detection (AD-369)

## Context

GPT-5.4 code review found that `useWebSocket.ts` hardcodes `ws://` for the
WebSocket URL. When ProbOS is served behind HTTPS (e.g., reverse proxy,
production deployment), browsers block insecure WebSocket connections to
secure origins. The protocol must match: `wss://` for HTTPS, `ws://` for HTTP.

**Identified by:** GPT-5.4 code review (2026-03-21)

---

## Changes

### File: `ui/src/hooks/useWebSocket.ts`

**Change:** Replace the hardcoded `ws://` protocol with dynamic detection
based on `window.location.protocol`.

Before (line 6):
```typescript
const WS_URL = `ws://${window.location.host}/ws/events`;
```

After:
```typescript
const WS_URL = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws/events`;
```

This is a single-line change. No other modifications needed.

---

## Tests

### File: `ui/src/hooks/__tests__/useWebSocket.test.ts`

If this test file exists, check whether it mocks `window.location` and verify
the test still passes. If no test file exists for this hook, no new test is
needed — this is a trivial one-line protocol detection change.

Run:
```bash
cd ui && npm run test
```

---

## Constraints

- Modify ONLY `ui/src/hooks/useWebSocket.ts`
- Change ONLY line 6 — do NOT refactor the hook
- Do NOT add new imports or dependencies
- Do NOT change the reconnection logic, backoff, or event handling
