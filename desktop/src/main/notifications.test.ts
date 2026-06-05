import { describe, it, expect, vi, beforeEach } from "vitest";

// AD-847: notifications.ts imports `Notification` from electron at module
// load. Mock it so the pure coercion + dispatch logic is testable in the
// node vitest environment without a real Electron runtime.
const shownNotifications: Array<{ title: string; body: string }> = [];
const clickHandlers: Array<() => void> = [];

vi.mock("electron", () => {
  class FakeNotification {
    title: string;
    body: string;
    constructor(opts: { title: string; body: string }) {
      this.title = opts.title;
      this.body = opts.body;
    }
    static isSupported(): boolean {
      return FakeNotification.supported;
    }
    static supported = true;
    on(event: string, cb: () => void): void {
      if (event === "click") clickHandlers.push(cb);
    }
    show(): void {
      shownNotifications.push({ title: this.title, body: this.body });
    }
  }
  return { Notification: FakeNotification };
});

import { coerceTaskDonePayload, notify } from "./notifications";
// Re-import the mocked class to flip `isSupported` per-test.
import { Notification } from "electron";

beforeEach(() => {
  shownNotifications.length = 0;
  clickHandlers.length = 0;
  (Notification as unknown as { supported: boolean }).supported = true;
});

describe("coerceTaskDonePayload", () => {
  it("accepts a well-formed payload with a route", () => {
    const r = coerceTaskDonePayload({
      title: "Task complete",
      body: "Summarize the scout report.",
      route: "/chat/yeoman-0",
    });
    expect(r).toEqual({
      title: "Task complete",
      body: "Summarize the scout report.",
      route: "/chat/yeoman-0",
    });
  });

  it("drops a blank route to undefined", () => {
    const r = coerceTaskDonePayload({ title: "t", body: "b", route: "" });
    expect(r).toEqual({ title: "t", body: "b", route: undefined });
  });

  it("rejects a missing/empty title", () => {
    expect(coerceTaskDonePayload({ title: "", body: "b" })).toBeNull();
    expect(coerceTaskDonePayload({ body: "b" })).toBeNull();
  });

  it("rejects a non-string body", () => {
    expect(coerceTaskDonePayload({ title: "t", body: 42 })).toBeNull();
  });

  it("rejects non-object payloads", () => {
    expect(coerceTaskDonePayload(null)).toBeNull();
    expect(coerceTaskDonePayload("nope")).toBeNull();
    expect(coerceTaskDonePayload(undefined)).toBeNull();
  });
});

describe("notify (AD-847 dispatch)", () => {
  it("shows a notification with the coerced title and body", () => {
    const activator = { showAndRoute: vi.fn() };
    notify({ title: "Done", body: "All set." }, activator);
    expect(shownNotifications).toEqual([{ title: "Done", body: "All set." }]);
  });

  it("routes on click when a route is present", () => {
    const showAndRoute = vi.fn();
    notify(
      { title: "Done", body: "All set.", route: "/chat/yeoman-0" },
      { showAndRoute },
    );
    expect(clickHandlers).toHaveLength(1);
    clickHandlers[0]();
    expect(showAndRoute).toHaveBeenCalledWith("/chat/yeoman-0");
  });

  it("registers no click handler without a route", () => {
    notify({ title: "Done", body: "All set." }, { showAndRoute: vi.fn() });
    expect(clickHandlers).toHaveLength(0);
  });

  it("suppresses the notification when OS support is absent", () => {
    (Notification as unknown as { supported: boolean }).supported = false;
    notify({ title: "Done", body: "All set." }, { showAndRoute: vi.fn() });
    expect(shownNotifications).toHaveLength(0);
  });
});
