import '@testing-library/jest-dom';
import { beforeEach } from 'vitest';

// BF-765: the speech ledger is module-scoped so a claim survives a remount,
// which means it also survives a TEST -- a reply spoken in one case is already
// claimed in the next. ~40 test files reach that surface, and resetting them
// one at a time missed one, found only under shuffled ordering.
//
// `speechLedgerStore` is deliberately importless so evaluating it here cannot
// pre-empt a test file's `vi.mock` hoisting. Importing `profileTranscript`
// here instead broke an unrelated `loadThreadMessages` test exactly that way.
import { resetSharedSpeechLedger } from '../components/profile/speechLedgerStore';

beforeEach(() => {
  resetSharedSpeechLedger();
});

// AD-722b: jsdom ships a `WebSocket` global that hangs in CONNECTING and
// never resolves to onopen/onerror in tests, which would cause SelfImageTab's
// new WS-first branch to stall the existing 7 poll-based tests. Each test
// that exercises the WS branch stubs WebSocket explicitly via
// `vi.stubGlobal('WebSocket', MockWebSocket)`. Tests that don't stub get the
// `undefined` WebSocket, which makes `new WebSocket(...)` throw inside the
// try/catch in SelfImageTab — falling back to the existing poll path.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
delete (globalThis as any).WebSocket;
