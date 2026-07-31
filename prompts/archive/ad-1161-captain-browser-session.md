# AD-1161 — Captain-initiated browser session

**Status:** Ready for Builder.
**Depends on:** AD-706 (BrowserTool), AD-1052a (MJPEG watch), AD-1052c (input forwarding), AD-1160 (`key_type`).
**Unblocks:** the Captain's live test — open a browser from the launcher, log into Word Online by hand, then ask an agent to type into it.

---

## 1. The gap

`GET /api/browser/sessions` **lists** sessions; nothing **creates** one. Sessions
only come into existence when an agent calls `goto`. So the Captain can open the
Browser workstation (Bridge → Engineering → Browser, `stations.tsx`), switch to
Watch, and find an empty picker — with no way to say "open a page for me".

The Captain's stated flow requires the opposite ordering: *the Captain* opens the
browser, logs in, and only then involves an agent.

## 2. Deliverable A — `BrowserTool.open_captain_session`

New public async method on `BrowserTool`, modelled **line for line** on the
existing `connect_bridge_session` (`tool.py`) — that is the proven shape: all
policy in the tool, the router a thin adapter, honest-degrade dict returns and
never a raise.

```python
async def open_captain_session(
    self, url: str, *, agent_id: str = "captain",
) -> dict[str, Any]:
```

Returns `{"opened": True, "session_id": ..., "streaming_url": ..., "url": ...,
"page_title": ...}` on success, `{"opened": False, "reason": "..."}` otherwise.

Requirements:

- **Reuse the existing `goto` path** so every guardrail binds automatically —
  `domain_allowlist`, `domain_denylist`, scheme validation, the session cap and
  the AD-706 audit log. Do **not** hand-roll navigation, and do **not**
  re-implement the allowlist check; route through whatever `_get_or_create_session`
  + the `goto` handler already do. If that requires calling the tool's own
  `invoke`, do that rather than reaching past it.
- Disabled tool ⇒ `{"opened": False, "reason": "Browser tool is disabled."}`.
- A denied or malformed URL ⇒ honest-degrade with the reason, no session left
  behind. **A rejected navigation must not leak a live session** — if a session
  was created before navigation failed, close it before returning.
- `agent_id="captain"` so the session is attributable and so
  `BrowserSession.agent_id` distinguishes Captain-opened from agent-opened.

**No `confirm` parameter.** The bridge needs one because it attaches to an
already-authenticated browser the Captain did not open for this purpose. Opening
a fresh session is the Captain acting on their own surface — a confirmation there
is friction without a corresponding risk. State this in the docstring so it is
not "hardened" later by analogy to the bridge.

## 3. Deliverable B — `POST /api/browser/sessions`

In `src/probos/routers/browser_stream.py`, beside the existing routes. Mirror
`connect_browser_bridge` exactly, including `dependencies=[Depends(require_crew_scope)]`.

```python
class OpenSessionRequest(BaseModel):
    url: str
```

Thin adapter: resolve `runtime.browser_tool`, honest-degrade when absent, else
return `await browser_tool.open_captain_session(body.url)`. **No policy in the
router** — that is the AD-1052b precedent and the reason the bridge route is four
lines.

## 4. Deliverable C — the Watch-mode affordance

`ui/src/components/workstation/BrowserWorkstation.tsx`.

- In **Watch** mode, add a URL field and an "Open" button that POSTs to the new
  endpoint, then refreshes the session list and **auto-selects the returned
  `session_id`** so the stream appears without a second click.
- Follow the file's existing deps-injection convention: add an `openSession`
  prop defaulting to a `_defaultOpenSession`, exactly as `fetchSessions` /
  `connectBridge` / `forwardInput` already do. Tests must not need network.
- Honest-degrade: render the `reason` string from an `{"opened": false}` response
  in the same place the bridge mode renders `bridgeReason`. Do not throw, do not
  leave a spinner running.
- **Default mode.** `useState<BrowserMode>('embedded')` becomes: `'watch'` when
  the backend reports the browser tool enabled, `'embedded'` otherwise. The
  workstation already fetches `/api/browser/sessions` (which returns `enabled`)
  — use that, do not add a second probe. Rationale: `embedded` is an iframe, and
  every interesting target (Word Online, OneDrive, most SaaS) sends
  `X-Frame-Options`/`frame-ancestors` and refuses to render. Landing the Captain
  on a mode that cannot show the thing they came for is the wrong default.

HXI rules apply: inline stroke SVG only (`strokeWidth: 1.5`, amber `#f0b060`
active, `#666680` inactive), **no emoji**, `data-testid` on every interactive
element.

## 5. Do NOT build

- No changes to `WorkstationPanel.tsx` layout / the fullscreen overlay. Making
  the workstation non-modal so browser and chat coexist is AD-1162.
- No saved/persisted workstation instances — that is AD-1163.
- No changes to `_BROWSER_LOOP_ACTIONS`, `classify_action`, or any action
  handler. Assert `_BROWSER_LOOP_ACTIONS` byte-identical.
- No `_action_state` changes (BF-692 stands separately).
- No new config fields. `browser_tool.enabled` already gates this.
- No bridge changes.

## 6. Acceptance criteria

- Backend tests in `tests/test_ad1161_captain_session.py`: happy path; disabled
  tool; denylisted domain; malformed URL; **a test proving a rejected navigation
  leaves no live session behind** (assert `list_sessions()` is unchanged).
- Route tests: happy path, tool-absent honest-degrade, and input validation —
  the API test requirement is 3 minimum per endpoint.
- UI tests in the existing BrowserWorkstation test file or a new sibling:
  Open-button success path auto-selects the session; `{"opened": false}` renders
  the reason; default mode is `watch` when enabled and `embedded` when not.
  Every UI change needs a Vitest test — the HXI has broken from untested UI
  changes before.
- `npx vitest run` green from `ui/`, and `npm run build` clean (`tsc -b` catches
  type drift Vitest does not).
- **Full Python suite.** Baseline **21,896 passed, 34 skipped**. Report the count.
- **Verify all changes comply with the Engineering Principles in
  `.github/copilot-instructions.md`.**

## 7. Commit

One commit. `git commit -F <file>`, never inline `-m`. **Do not `git add
config/system.yaml`** — skip-worktree (`S`); verify with `git ls-files -v
config/system.yaml`. Do not push; the Architect reviews first.
