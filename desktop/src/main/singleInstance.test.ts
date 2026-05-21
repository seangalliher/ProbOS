import { describe, it, expect, vi } from "vitest";
import {
  acquireSingleInstanceLock,
  decideSecondInstanceAction,
} from "./singleInstance";

describe("decideSecondInstanceAction", () => {
  it("extracts a probos:// argv and signals exit", () => {
    const r = decideSecondInstanceAction([
      "electron.exe",
      "--foo",
      "probos://chat",
    ]);
    expect(r.forwardedDeepLink).toBe("probos://chat");
    expect(r.shouldExit).toBe(true);
  });

  it("returns null deep-link when none present and still signals exit", () => {
    const r = decideSecondInstanceAction(["electron.exe", "--foo"]);
    expect(r.forwardedDeepLink).toBeNull();
    expect(r.shouldExit).toBe(true);
  });
});

describe("acquireSingleInstanceLock", () => {
  it("returns true and does not exit when lock acquired", () => {
    const exit = vi.fn();
    const got = acquireSingleInstanceLock({
      requestSingleInstanceLock: () => true,
      exit,
    });
    expect(got).toBe(true);
    expect(exit).not.toHaveBeenCalled();
  });

  it("returns false and exits with code 0 when lock is unavailable", () => {
    const exit = vi.fn();
    const got = acquireSingleInstanceLock({
      requestSingleInstanceLock: () => false,
      exit,
    });
    expect(got).toBe(false);
    expect(exit).toHaveBeenCalledWith(0);
  });
});
