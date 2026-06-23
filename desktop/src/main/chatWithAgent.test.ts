/**
 * AD-815b: tests for tray submenu + chatWithAgent helper.
 */

import { describe, expect, it, vi } from "vitest";
import {
  actionableCount,
  buildChatWithSubmenu,
  buildTrayMenu,
} from "./trayMenu";
import {
  startChatWithAgent,
  type ChatWithAgentClient,
  type Thread,
} from "./chatWithAgent";

function noop(): void {
  /* test stub */
}

const baseOpts = {
  status: "connected" as const,
  proactivePaused: false,
  viewMode: "compact" as const,
  onOpenRoute: noop,
  onToggleProactive: noop,
  onToggleViewMode: noop,
  onCheckForUpdates: noop,
  onResetSetup: noop,
  onQuit: noop,
};

describe("buildChatWithSubmenu", () => {
  it("returns empty when no agents supplied", () => {
    expect(buildChatWithSubmenu({})).toEqual([]);
  });

  it("returns empty when agents list is empty", () => {
    expect(buildChatWithSubmenu({ agents: [] })).toEqual([]);
  });

  it("builds one submenu item per agent", () => {
    const items = buildChatWithSubmenu({
      agents: [
        { id: "yao", name: "Yao" },
        { id: "ezri", name: "Ezri" },
      ],
    });
    expect(items).toHaveLength(1);
    expect(items[0].id).toBe("chat-with");
    expect(items[0].type).toBe("submenu");
    expect(items[0].submenu).toHaveLength(2);
    expect(items[0].submenu?.[0].label).toBe("Yao");
    expect(items[0].submenu?.[1].label).toBe("Ezri");
  });

  it("invokes onStartChatWithAgent when a submenu item is clicked", () => {
    const onStart = vi.fn();
    const items = buildChatWithSubmenu({
      agents: [{ id: "yao", name: "Yao" }],
      onStartChatWithAgent: onStart,
    });
    items[0].submenu?.[0].click?.();
    expect(onStart).toHaveBeenCalledWith("yao");
  });
});

describe("buildTrayMenu with AD-815b agents", () => {
  it("inserts the Chat-with submenu when agents are supplied", () => {
    const items = buildTrayMenu({
      ...baseOpts,
      agents: [{ id: "yao", name: "Yao" }],
    });
    const ids = items.map((i) => i.id);
    expect(ids).toContain("chat-with");
    const idx = ids.indexOf("chat-with");
    expect(ids[idx - 1]).toBe("quick-capture");
    expect(ids[idx + 1]).toBe("toggle-proactive");
    // 10 baseline + chat-with + AD-841d Management submenu.
    expect(actionableCount(items)).toBe(12);
  });

  it("preserves the original 10-item layout when agents is unset", () => {
    const items = buildTrayMenu(baseOpts);
    expect(actionableCount(items)).toBe(11);
    expect(items.map((i) => i.id)).not.toContain("chat-with");
    expect(items.map((i) => i.id)).toContain("management");
  });
});

// ---------------- chatWithAgent ----------------

function makeClient(threads: Thread[]): {
  client: ChatWithAgentClient;
  createCalls: Array<{ title: string; participants: string[] }>;
} {
  const createCalls: Array<{ title: string; participants: string[] }> = [];
  const client: ChatWithAgentClient = {
    listThreads: async () => threads,
    createThread: async (opts) => {
      createCalls.push(opts);
      return {
        id: "new-thread",
        title: opts.title,
        participants: opts.participants,
        archived: false,
        last_active_at: 0,
      };
    },
  };
  return { client, createCalls };
}

describe("startChatWithAgent", () => {
  it("creates a new thread when no 1:1 exists with this agent", async () => {
    const { client, createCalls } = makeClient([]);
    const id = await startChatWithAgent({ id: "yao", name: "Yao" }, client);
    expect(id).toBe("new-thread");
    expect(createCalls).toEqual([
      { title: "Chat with Yao", participants: ["yao"] },
    ]);
  });

  it("reuses the most-recently-active matching 1:1 thread", async () => {
    const threads: Thread[] = [
      {
        id: "t-old",
        title: "Chat with Yao",
        participants: ["yao"],
        archived: false,
        last_active_at: 100,
      },
      {
        id: "t-new",
        title: "Chat with Yao",
        participants: ["yao"],
        archived: false,
        last_active_at: 200,
      },
    ];
    const { client, createCalls } = makeClient(threads);
    const id = await startChatWithAgent({ id: "yao", name: "Yao" }, client);
    expect(id).toBe("t-new");
    expect(createCalls).toEqual([]);
  });

  it("ignores archived threads and creates a fresh one", async () => {
    const threads: Thread[] = [
      {
        id: "t-archived",
        title: "Chat with Yao",
        participants: ["yao"],
        archived: true,
        last_active_at: 500,
      },
    ];
    const { client, createCalls } = makeClient(threads);
    const id = await startChatWithAgent({ id: "yao", name: "Yao" }, client);
    expect(id).toBe("new-thread");
    expect(createCalls).toHaveLength(1);
  });

  it("ignores multi-participant threads when matching 1:1", async () => {
    const threads: Thread[] = [
      {
        id: "huddle",
        title: "Huddle",
        participants: ["yao", "ezri"],
        archived: false,
        last_active_at: 999,
      },
    ];
    const { client, createCalls } = makeClient(threads);
    const id = await startChatWithAgent({ id: "yao", name: "Yao" }, client);
    expect(id).toBe("new-thread");
    expect(createCalls).toHaveLength(1);
  });

  it("ignores threads where the single participant is a different agent", async () => {
    const threads: Thread[] = [
      {
        id: "t-ezri",
        title: "Chat with Ezri",
        participants: ["ezri"],
        archived: false,
        last_active_at: 999,
      },
    ];
    const { client } = makeClient(threads);
    const id = await startChatWithAgent({ id: "yao", name: "Yao" }, client);
    expect(id).toBe("new-thread");
  });
});
