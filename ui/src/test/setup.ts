import '@testing-library/jest-dom';

// AD-722b: jsdom ships a `WebSocket` global that hangs in CONNECTING and
// never resolves to onopen/onerror in tests, which would cause SelfImageTab's
// new WS-first branch to stall the existing 7 poll-based tests. Each test
// that exercises the WS branch stubs WebSocket explicitly via
// `vi.stubGlobal('WebSocket', MockWebSocket)`. Tests that don't stub get the
// `undefined` WebSocket, which makes `new WebSocket(...)` throw inside the
// try/catch in SelfImageTab — falling back to the existing poll path.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
delete (globalThis as any).WebSocket;
