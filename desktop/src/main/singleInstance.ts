/**
 * AD-759 single-instance lock helpers.
 *
 * Pure functions. The Electron-bound side-effects (`app.requestSingleInstanceLock`,
 * `app.on('second-instance', ...)`, `app.quit()`) live in `index.ts`; this module
 * holds the logic we want to unit-test.
 */

import { findDeepLinkInArgv } from "./deepLink.js";

export interface SecondInstanceForwardResult {
  forwardedDeepLink: string | null;
  shouldExit: boolean;
}

/**
 * Decide what the SECOND instance should do given its argv.
 *
 * v1 behavior: always exit (code 0), forward the deep-link payload (if any)
 * to the primary instance via the caller's IPC channel.
 */
export function decideSecondInstanceAction(
  argv: readonly string[],
): SecondInstanceForwardResult {
  const deepLink = findDeepLinkInArgv(argv);
  return {
    forwardedDeepLink: deepLink,
    shouldExit: true,
  };
}

export interface LockAcquireApi {
  requestSingleInstanceLock(): boolean;
  exit(code: number): void;
}

/**
 * Attempt to acquire the single-instance lock. If the lock is unavailable,
 * call `exit(0)` and return false. Returns true if this process is the primary.
 *
 * Caller is responsible for any pre-exit IPC forwarding (the OS-level forward
 * happens automatically via Electron's `second-instance` event on the primary).
 */
export function acquireSingleInstanceLock(app: LockAcquireApi): boolean {
  const gotLock = app.requestSingleInstanceLock();
  if (!gotLock) {
    app.exit(0);
    return false;
  }
  return true;
}
