import { describe, it, expect } from "vitest";
import { createConnectionStateMachine } from "./connectionStateMachine";

describe("createConnectionStateMachine", () => {
  it("initial state is 'connecting'", () => {
    const m = createConnectionStateMachine();
    expect(m.state).toBe("connecting");
  });

  it("transitions to 'connected' on load-success", () => {
    const m = createConnectionStateMachine();
    m.send({ type: "load-success" });
    expect(m.state).toBe("connected");
  });

  it("transitions to 'disconnected' on load-failure", () => {
    const m = createConnectionStateMachine();
    m.send({ type: "load-success" });
    m.send({ type: "load-failure", errorCode: -106 });
    expect(m.state).toBe("disconnected");
  });

  it("returns to 'connecting' on manual-retry from disconnected", () => {
    const m = createConnectionStateMachine();
    m.send({ type: "load-failure" });
    expect(m.state).toBe("disconnected");
    m.send({ type: "manual-retry" });
    expect(m.state).toBe("connecting");
  });

  it("subscribers fire only on actual state change", () => {
    const m = createConnectionStateMachine();
    const seen: string[] = [];
    m.subscribe((s) => seen.push(s));
    m.send({ type: "load-start" }); // already 'connecting', no change
    m.send({ type: "load-success" }); // -> connected
    m.send({ type: "load-success" }); // duplicate, no change
    m.send({ type: "load-failure" }); // -> disconnected
    expect(seen).toEqual(["connected", "disconnected"]);
  });

  it("unsubscribe stops notifications", () => {
    const m = createConnectionStateMachine();
    const seen: string[] = [];
    const unsub = m.subscribe((s) => seen.push(s));
    m.send({ type: "load-success" });
    unsub();
    m.send({ type: "load-failure" });
    expect(seen).toEqual(["connected"]);
  });
});
