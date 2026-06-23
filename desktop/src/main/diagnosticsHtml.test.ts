import { describe, it, expect } from "vitest";
import { diagnosticsHtml } from "./diagnosticsHtml";

describe("diagnosticsHtml", () => {
  it("renders the runtime URL", () => {
    const html = diagnosticsHtml({ runtimeUrl: "http://127.0.0.1:8765", status: "connected" });
    expect(html).toContain("http://127.0.0.1:8765");
  });

  it("renders the connection status label for each state", () => {
    expect(diagnosticsHtml({ runtimeUrl: "http://x", status: "connected" })).toContain("Connected");
    expect(diagnosticsHtml({ runtimeUrl: "http://x", status: "connecting" })).toContain("Connecting");
    expect(diagnosticsHtml({ runtimeUrl: "http://x", status: "disconnected" })).toContain("Disconnected");
  });

  it("wires the Retry button to the existing retryConnect bridge", () => {
    const html = diagnosticsHtml({ runtimeUrl: "http://x", status: "disconnected" });
    expect(html).toContain("retryConnect");
  });

  it("uses no emoji (HXI SVG/markup discipline)", () => {
    const html = diagnosticsHtml({ runtimeUrl: "http://x", status: "connected" });
    expect(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/u.test(html)).toBe(false);
  });
});
