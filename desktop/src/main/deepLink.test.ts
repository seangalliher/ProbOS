import { describe, it, expect } from "vitest";
import {
  parseDeepLink,
  findDeepLinkInArgv,
  MAX_DEEP_LINK_LENGTH,
} from "./deepLink";

describe("parseDeepLink", () => {
  it("accepts a simple probos://chat link", () => {
    const r = parseDeepLink("probos://chat");
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.route).toBe("/chat");
  });

  it("accepts a probos://briefing?date=today link", () => {
    const r = parseDeepLink("probos://briefing?date=today");
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.route).toBe("/briefing?date=today");
  });

  it("accepts multi-segment paths like probos://chat/agent_1", () => {
    const r = parseDeepLink("probos://chat/agent_1");
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.route).toBe("/chat/agent_1");
  });

  it("rejects traversal: probos://../etc/passwd", () => {
    const r = parseDeepLink("probos://../etc/passwd");
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("traversal");
  });

  it("rejects URLs longer than 2048 chars", () => {
    const longTail = "a".repeat(MAX_DEEP_LINK_LENGTH + 50);
    const r = parseDeepLink(`probos://chat/${longTail}`);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("over-length");
  });

  it("rejects http:// scheme", () => {
    const r = parseDeepLink("http://chat");
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("bad-scheme");
  });

  it("rejects control characters in path", () => {
    const r = parseDeepLink("probos://chat/foo\u0001bar");
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("control-char");
  });

  it("rejects shell metacharacters", () => {
    const r = parseDeepLink("probos://chat;rm-rf");
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("shell-metachar");
  });

  it("rejects empty path probos://", () => {
    const r = parseDeepLink("probos://");
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("empty-path");
  });

  it("rejects malformed query without =", () => {
    const r = parseDeepLink("probos://briefing?date");
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.reason).toBe("bad-query-pair");
  });
});

describe("findDeepLinkInArgv", () => {
  it("returns the first probos:// arg", () => {
    expect(
      findDeepLinkInArgv(["electron.exe", "--foo", "probos://chat"]),
    ).toBe("probos://chat");
  });

  it("returns null when no probos:// arg present", () => {
    expect(findDeepLinkInArgv(["electron.exe", "--foo"])).toBeNull();
  });
});
