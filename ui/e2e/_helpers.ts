// AD-941: shared fixtures + helpers for the chat-collaboration e2e specs.
//
// Deterministic and backend-free. Each spec:
//   1. registers the REST mock (`mockChatApi`) BEFORE navigation so the App's
//      mount-time fetches (config / profile / threads) are intercepted;
//   2. navigates + waits for the DEV store seam (`gotoApp`);
//   3. seeds crew into the store (`seedAgents`) through `window.__store`.
//
// `Map`s cannot cross `page.evaluate` as Maps, so every helper passes plain
// arrays and rebuilds the `Map` INSIDE the evaluate (useStore stores `agents`
// and `chatThreads` as `Map`s). No live backend (:18900); no real-data mutation.
import type { Page } from '@playwright/test';

// ── Fixtures ───────────────────────────────────────────────────────────────

/** A serializable crew agent matching the store's `Agent` shape (the fields the
 *  chat components actually read: id, callsign, isCrew, department). Mirrors the
 *  Vitest `mkAgent` helper so the e2e + unit fixtures agree. */
export interface AgentFixture {
  id: string;
  agentType: string;
  callsign: string;
  displayName: string;
  pool: string;
  state: string;
  confidence: number;
  trust: number;
  tier: string;
  isCrew: boolean;
  position: [number, number, number];
  department: string;
}

export function mkAgent(id: string, callsign: string, department = 'bridge'): AgentFixture {
  return {
    id,
    agentType: 'crew',
    callsign,
    displayName: '',
    pool: 'bridge',
    state: 'active',
    confidence: 1,
    trust: 0.5,
    tier: 'domain',
    isCrew: true,
    position: [0, 0, 0],
    department,
  };
}

export const EZRI = mkAgent('ezri', 'Ezri', 'science');
export const YEO = mkAgent('yeo', 'Yeo', 'bridge');
// A couple of extra crew so the New-chat / add-participant picker has a list.
export const KIRA = mkAgent('kira', 'Kira', 'security');
export const JADZIA = mkAgent('jadzia', 'Jadzia', 'science');

export const CREW: AgentFixture[] = [EZRI, YEO, KIRA, JADZIA];

/** A serializable chat thread matching `AD791aChatThreadView`. */
export interface ThreadFixture {
  id: string;
  title: string;
  participants: string[];
  created_at: number;
  last_active_at: number;
  metadata?: Record<string, unknown>;
  task_id?: string;
}

export function mkThread(
  id: string,
  title: string,
  participants: string[],
  extra: Partial<ThreadFixture> = {},
): ThreadFixture {
  return { id, title, participants, created_at: 0, last_active_at: 0, ...extra };
}

/** A persisted thread message as returned by GET /api/threads/{id}/messages
 *  (`ThreadMessageDTO`: {id, thread_id, author_id, role, body, created_at, metadata}). */
export interface MessageFixture {
  id: string;
  thread_id: string;
  author_id: string;
  role: string;
  body: string;
  created_at: number;
  metadata?: Record<string, unknown>;
}

export function mkMessage(
  id: string,
  threadId: string,
  authorId: string,
  role: string,
  body: string,
  createdAt = 1000,
): MessageFixture {
  return { id, thread_id: threadId, author_id: authorId, role, body, created_at: createdAt, metadata: {} };
}

// ── REST mock ────────────────────────────────────────────────────────────────

export interface MockChatApiOptions {
  threads?: ThreadFixture[];
  messagesByThread?: Record<string, MessageFixture[]>;
  /** The thread returned by POST /api/threads (the new group). */
  createdThread?: ThreadFixture;
}

const JSON_HEADERS = { 'Content-Type': 'application/json' };

/** Mock the `/api/**` REST surface with a single route that branches on method
 *  + pathname. The chat endpoints the specs assert are fulfilled with valid
 *  shapes; every OTHER `/api` endpoint the full App touches on mount is
 *  ABORTED — i.e. it behaves exactly as if no backend were present, which
 *  drives each component down its Tier-2 honest-degrade path (keeping its safe
 *  default state) instead of feeding it a malformed body that would crash a
 *  non-optional property access during mount. WebSocket (`/ws`) is not
 *  intercepted (it simply never connects, which the App already tolerates). */
export async function mockChatApi(page: Page, opts: MockChatApiOptions = {}): Promise<void> {
  const threads = opts.threads ?? [];
  const messagesByThread = opts.messagesByThread ?? {};
  const threadsById = new Map(threads.map((t) => [t.id, t]));

  await page.route('**/api/**', async (route) => {
    const req = route.request();
    const method = req.method();
    const path = new URL(req.url()).pathname;

    const fulfill = (body: unknown): Promise<void> =>
      route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify(body) });

    let parsedBody: Record<string, unknown> = {};
    if (method === 'POST' || method === 'PATCH') {
      try {
        parsedBody = (req.postDataJSON() as Record<string, unknown>) ?? {};
      } catch {
        parsedBody = {};
      }
    }

    // GET /api/threads/{id}/messages -> {thread_id, messages}
    let m = path.match(/^\/api\/threads\/([^/]+)\/messages$/);
    if (m && method === 'GET') {
      const id = decodeURIComponent(m[1]);
      return fulfill({ thread_id: id, messages: messagesByThread[id] ?? [] });
    }

    // POST /api/threads/{id}/messages -> appended message dict (+ empty fan-out)
    if (m && method === 'POST') {
      const id = decodeURIComponent(m[1]);
      return fulfill({
        id: `srv-${Date.now()}`,
        thread_id: id,
        ...parsedBody,
        per_agent_replies: [],
      });
    }

    // POST /api/threads/{id}/participants -> updated thread
    m = path.match(/^\/api\/threads\/([^/]+)\/participants$/);
    if (m && method === 'POST') {
      const id = decodeURIComponent(m[1]);
      const base = threadsById.get(id) ?? mkThread(id, 'Room', []);
      const agentId = typeof parsedBody.agent_id === 'string' ? parsedBody.agent_id : '';
      const participants = base.participants.includes(agentId)
        ? base.participants
        : [...base.participants, agentId];
      return fulfill({ ...base, participants, last_active_at: 1 });
    }

    // PATCH /api/threads/{id} -> merged thread (meeting_active / rename)
    m = path.match(/^\/api\/threads\/([^/]+)$/);
    if (m && method === 'PATCH') {
      const id = decodeURIComponent(m[1]);
      const base = threadsById.get(id) ?? mkThread(id, 'Room', []);
      const metadata = { ...(base.metadata ?? {}) } as Record<string, unknown>;
      if ('meeting_active' in parsedBody) metadata.meeting_active = parsedBody.meeting_active;
      const title = typeof parsedBody.title === 'string' ? parsedBody.title : base.title;
      const merged = { ...base, title, metadata, last_active_at: 1 };
      threadsById.set(id, merged);
      return fulfill(merged);
    }

    // GET /api/threads -> {threads};  POST /api/threads -> created thread DIRECT
    if (/^\/api\/threads$/.test(path)) {
      if (method === 'POST') {
        return fulfill(opts.createdThread ?? mkThread('created', 'New group chat', []));
      }
      return fulfill({ threads });
    }

    // Every other endpoint the full App mounts (config / perception budget /
    // wardroom dms / profile / history / inputs / ...): abort, so the component
    // takes its no-backend degrade path rather than receiving a wrong-shaped
    // body. A blanket `{}`/`[]` here crashes mount (e.g. VisionBudgetBadge reads
    // `calls_today.vision`; the dm sidebar `.map`s the response).
    return route.abort();
  });
}

// ── Store seeding (through the DEV `window.__store` seam) ─────────────────────

/** Navigate to the app and wait for the DEV store seam to be installed.
 *  `window.__store = useStore` is set at module import under `import.meta.env.DEV`
 *  (useStore.ts:2654), so it exists as soon as the bundle loads — before React
 *  mounts — which is all the seeding helpers need. The first-run WelcomeOverlay
 *  (a full-screen `inset:0; zIndex:100` click-catcher gated on
 *  `!localStorage.hxi_seen_intro`) is pre-dismissed so it never intercepts the
 *  spec's clicks. */
export async function gotoApp(page: Page): Promise<void> {
  // Set the "seen intro" flag BEFORE any page script runs so the store
  // initializes showIntro=false and the overlay never renders.
  await page.addInitScript(() => {
    try {
      localStorage.setItem('hxi_seen_intro', 'true');
    } catch {
      /* localStorage unavailable */
    }
  });
  await page.goto('/');
  await page.waitForFunction(() => Boolean((window as unknown as { __store?: unknown }).__store));
  // Belt-and-suspenders: clear the intro flag in the live store too.
  await page.evaluate(() => {
    const store = (window as unknown as {
      __store: { getState: () => { setShowIntro?: (v: boolean) => void } };
    }).__store;
    store.getState().setShowIntro?.(false);
  });
}

/** Seed the crew roster. Builds the `agents` Map INSIDE the evaluate (Maps
 *  cannot cross `page.evaluate`). */
export async function seedAgents(page: Page, agents: AgentFixture[]): Promise<void> {
  await page.evaluate((arr) => {
    const store = (window as unknown as { __store: { setState: (s: unknown) => void } }).__store;
    store.setState({ agents: new Map(arr.map((a: AgentFixture) => [a.id, a])) });
  }, agents);
}

/** Seed `chatThreads` (the Map read by GroupChatHeader / MeetingView / the
 *  meetingActive selector) and open the CHATS panel. The panel's row list is
 *  driven by its own `listThreads()` fetch (mock GET /api/threads), so this is
 *  for the post-open thread context. */
export async function seedThreads(page: Page, threads: ThreadFixture[]): Promise<void> {
  await page.evaluate((arr) => {
    const store = (window as unknown as { __store: { setState: (s: unknown) => void } }).__store;
    store.setState({
      chatThreads: new Map(arr.map((t: ThreadFixture) => [t.id, t])),
      chatsOpen: true,
    });
  }, threads);
}

/** Open the CHATS panel (the `openChats` action sets `chatsOpen`, which triggers
 *  the panel's listThreads fetch -> the mocked GET /api/threads). */
export async function openChats(page: Page): Promise<void> {
  await page.evaluate(() => {
    const store = (window as unknown as {
      __store: { getState: () => { openChats: () => void } };
    }).__store;
    store.getState().openChats();
  });
}

/** Open an agent's profile chat tab with no active thread (a fresh/empty 1:1) —
 *  drives ProfileChatTab's `!activeThreadId` branch (EmptyChatAddPeople). */
export async function openEmptyOneToOne(page: Page, agentId: string): Promise<void> {
  await page.evaluate((id) => {
    const store = (window as unknown as {
      __store: { getState: () => { openAgentProfile: (id: string) => void } };
    }).__store;
    store.getState().openAgentProfile(id);
  }, agentId);
}

/** Open a GROUP chat directly via the store (hydrate the thread + the AD-937
 *  group override) WITHOUT opening the CHATS panel — so the panel never
 *  overlaps the in-chat header controls (e.g. the meeting toggle). */
export async function openGroupChat(page: Page, hostId: string, thread: ThreadFixture): Promise<void> {
  await page.evaluate(
    ({ host, t }) => {
      const store = (window as unknown as {
        __store: {
          getState: () => {
            setChatThread: (t: unknown) => void;
            openGroupChatThread: (host: string, id: string) => void;
          };
        };
      }).__store;
      const st = store.getState();
      st.setChatThread(t);
      st.openGroupChatThread(host, t.id);
    },
    { host: hostId, t: thread },
  );
}
