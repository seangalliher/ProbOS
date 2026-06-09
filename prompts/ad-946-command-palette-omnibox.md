# AD-946 — The `Ask ProbOS…` omnibox becomes the Ship's-Computer command palette (Bridge as Ship's Computer)

**Target repo:** OSS (`d:\ProbOS`). **This AD = AD-946.** GitHub epic `seangalliher/ProbOS#873`; this issue `#881`.
**Mode:** Builder. Frontend only (UI). Commit local. **No push** (the Captain decides the push).
**Builds on:** AD-943 (`d373501b`) — the typed `CommandStation` registry; AD-944 (`6ddecf55`) — the 9 toolbar
launches became `StationAction`s; AD-945 (`f3843d8a`) — the bottom-right cluster folded into the Engineering
`config`. **This is the FINAL wave of the epic.** Forward marker only (DO NOT build): **AD-946a** — *voice*
command of stations ("Computer, open the Work Board") + *config* palette entries; it reuses this AD's command
registry + match helper.

## Goal
Upgrade the `Ask ProbOS…` omnibox so the **keyboard** can drive Bridge **station launches** directly: the Captain
types a leading `>` to enter command mode, the matching launches surface in a dropdown above the input, and Enter
runs the highlighted one (the **same** store action the Bridge fires). This is the Ship's Computer's keyboard
fallback — voice + camera are the primary modes; the palette satisfies the HXI Cockpit-View manual-override (#11)
and Self-Sufficiency principles. **Browse/discovery lives on the Bridge stations; intent/speed lives in this
palette.**

**Hard guarantee:** a plain natural-language question (the dominant case — anything NOT starting with `>`)
submits **byte-for-byte exactly as it does today**. The palette is an *additional* affordance, not a replacement
for the NL `/api/chat` submit path.

Reference: the 11 HXI Design Principles in `.github/copilot-instructions.md` (esp. #3 no-emoji stroke-SVG glyphs,
#6 the canvas IS the information, #11 agentic-first / manual-override).

---

## Verified current shape (grep evidence in the footer)

### 1. The omnibox host — `ui/src/components/IntentSurface.tsx`
- **The input** (the live omnibox) renders at `:2174`–`:2189`:
  ```tsx
  <input
    ref={inputRef}
    value={input}
    onChange={(e) => handleInputChange(e.target.value)}
    onKeyDown={handleKeyDown}
    onPaste={handlePaste}
    onBlur={() => { setTimeout(() => setPickerOpen(false), 150); }}
    placeholder="Ask ProbOS..."
    style={{ … }}
  />
  ```
  inside `<form onSubmit={handleSubmit} …>` (`:2013`). The collapsed pill ("Ask ProbOS...") is at `:2399`–`:2400`.
- **`handleSubmit`** (`:294`): `e.preventDefault(); const text = input.trim(); if (!text) return;` → **a leading-sigil
  client-side command is ALREADY intercepted before NL submit** — the `/grant ` branch at `:302` parses + POSTs and
  `return`s without sending an NL message. The default NL path (`:356`+) is `addChatMessage('user', text);
  setInput(''); incPendingRequests(); … fetch('/api/chat', …)`. **`>` is a free sigil** — the only client-side
  guard is `/grant ` (grep `startsWith('` in the file: `/grant `, plus `@` for the picker and `image/`/`audio/`/`(`
  unrelated).
- **`handleKeyDown`** (`:433`): handles `Escape` (wake-word cancel → picker close → collapse), and when
  `pickerOpen && pickerMatches.length > 0`, `ArrowDown`/`ArrowUp`/`Tab`/`Enter` drive the @-picker (`:454`–`:476`).
  **Plain `Enter` with no picker open falls through to the native form submit → `handleSubmit`.**
- **`handleInputChange`** (`:514`): sets `input`, then detects an `@<prefix>` *tail* to open the @-picker (`:515`).
- **Local state** the palette joins: `input`/`setInput` (`:46`), `active` (`:47`), the @-picker trio
  `pickerOpen`/`pickerPrefix`/`pickerIndex` (`:64`–`:66`), `inputRef` (`:56`).
- **The Spotlight landing**: the `pendingChar` effect (`:105`–`:112`) — when `pendingChar && !active`, it opens the
  shell, seeds `input` with the typed char, and focuses. So typing `>` anywhere opens the omnibox with `>` already
  in the input.

### 2. The `triggerInput` seam (do NOT add a competing listener)
- `ui/src/App.tsx:43`–`:56`: ONE global `keydown` handler — if no `INPUT`/`TEXTAREA` is focused and the key is a
  single printable char (no ctrl/meta/alt), it calls `useStore.getState().triggerInput(e.key)` (`:51`).
- `ui/src/store/useStore.ts`: `triggerInput: (char) => set({ pendingChar: char })` (`:1613`); `consumePendingChar`
  (`:1614`–`:1618`) reads + clears `pendingChar` (`pendingChar` state at `:445`, init `''` at `:927`).
- IntentSurface consumes `pendingChar` (§1 above) → the palette integrates by reading the **same** `input` state;
  **no new key listener.**

### 3. The station registry IS the command source of truth — `ui/src/components/bridge/stations.tsx`
- `export function buildBridgeStations(ctx: { dmChannelCount: number; kanbanCount: number; totalUnread: number }):
  CommandStation[]` (`:68`–`:71`). Already imported + called by `BridgePanel.tsx` (`:9`, `:217`); **IntentSurface
  already imports `BridgePanel` (`:22`), so `stations.tsx` is already in IntentSurface's module graph — no new
  cycle.**
- `CommandStation` (`:36`–`:46`): `{ id, title, accent, defaultOpen, count?, onExpand?, body?, actions[], config[] }`.
  `StationAction` (`:19`–`:24`): `{ id, label, onInvoke: () => void, count? }`. `StationConfig` (`:27`–`:31`):
  `{ id, label, render }`.
- **Every Captain-facing launch in the registry** (verified against `buildBridgeStations` + `stations.test.tsx`):

  | Station (title) | `onExpand` (primary) | `actions` (`id` → label) |
  |---|---|---|
  | Communications | open Ward Room (channels) | `ward-room-action`→**Ward Room** (count=totalUnread), `chats-toggle`→**Chats** |
  | Personnel | — | `crew-action`→**Crew**, `personnel-toggle`→**Personnel**, `behavioral-metrics-toggle`→**Metrics** |
  | Science | — | `notebooks-toggle`→**Notebooks**, `knowledge-browser-toggle`→**Records**, `spatial-explorer-toggle`→**Explorer** |
  | Operations | `setState({ mainViewer: 'work' })` (Work Board) | *(none)* |
  | Engineering | `setState({ mainViewer: 'system' })` (System) | *(none)* — has `config:[environment]` |
  | Command | — | `topnav-settings`→**Settings** |

  Every `onInvoke`/`onExpand` is a pure global closure (`useStore.getState().openX()` / `useStore.setState(…)` /
  `useSettingsStore.getState().openSettings()`), so it runs identically when invoked from IntentSurface.
- **ctx assembly** the omnibox host mirrors (from `BridgePanel.tsx`): `dmChannelCount: wardRoomDmChannels.length`
  (`:108`,`:218`); `kanbanCount: (missionControlTasks ?? []).length` (`:107`,`:137`,`:219`); `totalUnread:
  Object.values(wardRoomUnread ?? {}).reduce((s,n)=>s+n,0)` (`:110`–`:111`,`:220`).

### 4. The keyboard-nav precedent to MIRROR — `ui/src/components/profile/AddParticipantPopover.tsx`
- `handleKeyDown` (`:91`–`:107`): `ArrowDown`→`min(i+1, len-1)`, `ArrowUp`→`max(i-1, 0)`, `Enter`/`Tab`→run
  `matches[index]`, `Escape`→close. Reset index to 0 when the filter changes. `scrollIntoView` guarded for jsdom
  (`:82`–`:88`). Rows: amber active wash `rgba(240,176,96,0.12)` / `#f0b060` text, dim `#666680`, **no emoji**.
- The in-host @-picker (IntentSurface `:454`–`:476`) is the *shared-input* sibling precedent (nav state lives on the
  host input). The palette mirrors **both**: nav state on the host (like the @-picker), row a11y/scroll-guard like
  `AddParticipantPopover`.

### 5. No existing palette/command-menu UI
Grep `palette|commandMenu|CommandPalette|slashCommand` across `ui/src` → **0 matches.** Clean build, no duplication.

---

## Design decisions (documented)

### A. Trigger model — **a leading `>` prefix (VS Code-style command mode).**  ✅ chosen
Evaluated: **(a)** always-on dropdown under every keystroke — *rejected*: a substring match fires on ordinary
questions ("what is the **engineer**'s trust" surfaces *Engineering/System*), so the palette would pop under nearly
every NL sentence and risks an accidental Enter-run; making NL safe then forces a "no row highlighted by default"
rule — noisy. **(c)** always-on fuzzy-ranked — *rejected*: same noise, worse. **(b) `>` prefix** — **chosen**: it
gives a **hard, zero-risk boundary** for the NL guarantee (anything not starting with `>` is byte-for-byte the
current path), it **reuses the existing leading-sigil interception** (`/grant`), it is the literal VS Code command
palette mental model for a developer Captain, and it matches the epic's "intent/speed lives in the palette,
discovery lives on the Bridge" framing (no always-on discovery needed in the omnibox). `>` is chosen over `/` to
avoid colliding with the backend slash-command namespace (`/grant`).

The Spotlight seam carries it for free: typing `>` while collapsed → `triggerInput('>')` → `pendingChar` → the
shell opens with `>` seeded (§2). **The placeholder string stays byte-identical `"Ask ProbOS..."`** — the AD-719/941
tests select the input by `input[placeholder="Ask ProbOS..."]`; changing it is a regression. (Optional, low
priority: a subtle inline hint `› run a command` shown only while `input === '>'`; MUST NOT alter the placeholder.)

### B. Command resolution — a small **pure** module `ui/src/components/bridge/paletteCommands.ts`
Two pure, unit-testable functions. The command list is derived from `buildBridgeStations(ctx)` — **one source of
truth, no hand-duplicated list.**

- `buildPaletteCommands(stations)` — flatten the registry into a flat launch list. **Rule: a station contributes its
  discrete `actions` when it has any; otherwise its primary `onExpand` launch.** This (i) covers every
  Captain-facing launch, (ii) avoids a near-duplicate (Communications' `onExpand` and its `ward-room-action` both
  open the Ward Room — the action wins, the onExpand is skipped), and (iii) makes the body-only stations
  (Operations/Work Board, Engineering/System) reachable. **`config` items are EXCLUDED** (forward marker AD-946a).
  → 11 commands: Ward Room, Chats, Crew, Personnel, Metrics, Notebooks, Records, Explorer, **Work Board**, **System**,
  Settings.
- `matchPaletteCommands(query, commands)` — case-insensitive, every whitespace term must be a substring of the
  haystack `` `${station} ${label}` `` (so "ward"→Ward Room, "work"→Operations/Work Board, "science records"→
  Records, "settings"→Settings). **Empty query → `[]`** (no command mode until the Captain types after `>`).

To make the body-only launches read as the Captain names them ("**work board**", "**system**") while keeping the
registry the single source of their labels, **add ONE optional field to the descriptor**: `onExpandLabel?: string`
on `CommandStation`, set `operations → 'Work Board'`, `engineering → 'System'`. The onExpand command's label is
`st.onExpandLabel ?? st.title`. *(Rejected alternative: an alias map inside `paletteCommands.ts` — that would be a
second, hand-maintained label list, the exact thing the epic forbids.)* This field is **purely additive** —
`BridgePanel` renders `st.title` for the header and `st.onExpand` for the Expand affordance and **never reads
`onExpandLabel`**, so AD-943/944/945 render is unchanged.

### C. Running a command — call the registry's invoke; v1 = ACTIONS + onExpand primaries, NOT config
Enter runs the highlighted command's `.run()` (the registry's `action.onInvoke` or `station.onExpand`). `config`
panels (Environment / DM-rank) render inline and are not unambiguous "launches" — deferred to AD-946a alongside
voice. v1 is launches only.

### D. Accessibility + HXI #3
Keyboard-first; the dropdown is `role="listbox"`, rows `role="option"` + `aria-selected`; stroke-SVG `ChevronRight`
glyph (reuse `./icons/Glyphs`, the same glyph `StationActionRow` uses); amber active `#f0b060` /
`rgba(240,176,96,0.12)`, dim `#666680`; **NO emoji.**

---

## Section 1 — NEW FILE: `ui/src/components/bridge/paletteCommands.ts` (pure helpers)

```ts
/* AD-946: flatten the Ship's-Computer command-station registry into a flat,
 * keyboard-searchable launch list. Pure + presentation-free — the omnibox
 * command palette (IntentSurface) and the forthcoming voice command of stations
 * (AD-946a) both consume this. Single source of truth = buildBridgeStations. */
import type { CommandStation } from './stations';

/** A flat, runnable launch derived from the station registry. */
export interface PaletteCommand {
  id: string;        // stable: the action.id, or `${stationId}:expand` for an onExpand launch
  label: string;     // what the Captain reads / what Enter runs
  station: string;   // the station title (grouping + the front of the match haystack)
  run: () => void;   // the registry invoke (action.onInvoke or station.onExpand)
}

/** Flatten the registry: a station contributes its discrete ACTIONS when it has
 *  any, otherwise its primary onExpand launch (Work Board / System). CONFIG
 *  panels are excluded (forward marker AD-946a). */
export function buildPaletteCommands(stations: CommandStation[]): PaletteCommand[] {
  const out: PaletteCommand[] = [];
  for (const st of stations) {
    if (st.actions.length > 0) {
      for (const a of st.actions) {
        out.push({ id: a.id, label: a.label, station: st.title, run: a.onInvoke });
      }
    } else if (st.onExpand) {
      out.push({
        id: `${st.id}:expand`,
        label: st.onExpandLabel ?? st.title,
        station: st.title,
        run: st.onExpand,
      });
    }
  }
  return out;
}

/** Case-insensitive token-AND substring match over `${station} ${label}`.
 *  Empty/whitespace query → [] (no command mode until the Captain types). */
export function matchPaletteCommands(
  query: string,
  commands: PaletteCommand[],
): PaletteCommand[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  const terms = q.split(/\s+/);
  return commands.filter((c) => {
    const hay = `${c.station} ${c.label}`.toLowerCase();
    return terms.every((t) => hay.includes(t));
  });
}
```

## Section 2 — `ui/src/components/bridge/stations.tsx`: add the optional `onExpandLabel`

**2a.** In `interface CommandStation` (after `onExpand?`), add the additive field:
```ts
  onExpand?: () => void;     // primary launch (the section Expand affordance)
  onExpandLabel?: string;    // AD-946: palette label for the onExpand launch (e.g. "Work Board")
```
**2b.** On the `operations` station object add `onExpandLabel: 'Work Board',` (next to its `onExpand`).
**2c.** On the `engineering` station object add `onExpandLabel: 'System',` (next to its `onExpand`).
*(No other change to `stations.tsx`. `BridgePanel` does not read this field.)*

## Section 3 — NEW FILE: `ui/src/components/CommandPalette.tsx` (presentational listbox)

A pure, props-driven dropdown (no store coupling) mirroring `AddParticipantPopover`'s rows + a11y. Nav state stays
on the host (IntentSurface), like the @-picker.

- Props: `{ matches: PaletteCommand[]; activeIndex: number; onHover: (i: number) => void; onRun: (cmd:
  PaletteCommand) => void; }`.
- Render `role="listbox"` `aria-label="Bridge commands"`, `data-testid="command-palette"`. Each row:
  `role="option"`, `aria-selected={i === activeIndex}`, `data-testid="command-palette-row"`, `data-cmd-index={i}`,
  `onMouseDown={(e) => { e.preventDefault(); onRun(cmd); }}` (mouse-confirm without losing input focus, like the
  @-picker), `onMouseEnter={() => onHover(i)}`. Leading `<ChevronRight size={12} />` (stroke-SVG, from
  `./icons/Glyphs`), the `label` (amber `#f0b060` when active else `#e0dcd4`), and the `station` as a dim
  right-aligned tag (`#666680`, uppercase). Active row background `rgba(240,176,96,0.12)`.
- Empty state when `matches.length === 0`: a single dim row "No matching command." (mirror
  `AddParticipantPopover`'s "No crew to add.").
- **NO emoji** (HXI #3).

## Section 4 — `ui/src/components/IntentSurface.tsx`: wire the palette

**4a. Imports** (top, with the other `./` imports):
```tsx
import { buildBridgeStations } from './bridge/stations';
import { buildPaletteCommands, matchPaletteCommands, type PaletteCommand } from './bridge/paletteCommands';
import { CommandPalette } from './CommandPalette';
```
**4b. Selectors + derived command list** (near the other `useStore((s) => …)` selectors): add
`wardRoomDmChannels`, `missionControlTasks`, `wardRoomUnread`, then memoize the command list (read-only, no new
store state):
```tsx
const wardRoomDmChannels = useStore((s) => s.wardRoomDmChannels);
const missionControlTasks = useStore((s) => s.missionControlTasks);
const wardRoomUnread = useStore((s) => s.wardRoomUnread);
const paletteCommands = useMemo<PaletteCommand[]>(() => {
  const totalUnread = Object.values(wardRoomUnread ?? {}).reduce((sum, n) => sum + n, 0);
  return buildPaletteCommands(buildBridgeStations({
    dmChannelCount: (wardRoomDmChannels ?? []).length,
    kanbanCount: (missionControlTasks ?? []).length,
    totalUnread,
  }));
}, [wardRoomDmChannels, missionControlTasks, wardRoomUnread]);
```
**4c. Palette local state** (with the @-picker state): `const [paletteOpen, setPaletteOpen] = useState(false);
const [paletteIndex, setPaletteIndex] = useState(0);`. Derive matches inline:
```tsx
const paletteMatches = paletteOpen ? matchPaletteCommands(input.slice(1), paletteCommands) : [];
```
**4d. `handleInputChange`** — palette mode is exclusive with the @-picker. At the **top** of the function, before
the `@`-tail block:
```tsx
function handleInputChange(value: string) {
  setInput(value);
  // AD-946: leading '>' enters command mode (exclusive with the @-picker).
  if (value.startsWith('>')) {
    setPaletteOpen(true);
    setPaletteIndex(0);
    setPickerOpen(false);
    return;
  }
  if (paletteOpen) setPaletteOpen(false);
  const tail = value.split(/\s+/).pop() ?? '';
  …unchanged @-picker detection…
}
```
**4e. `handleKeyDown`** — add a palette branch that returns BEFORE the @-picker branch (they are mutually
exclusive; this is belt-and-suspenders). Mirror `AddParticipantPopover`/the @-picker:
```tsx
// AD-946: command palette keyboard nav (leading '>'). Mirrors the @-picker.
if (paletteOpen && paletteMatches.length > 0) {
  if (e.key === 'ArrowDown') { e.preventDefault(); setPaletteIndex((i) => (i + 1) % paletteMatches.length); return; }
  if (e.key === 'ArrowUp')   { e.preventDefault(); setPaletteIndex((i) => (i - 1 + paletteMatches.length) % paletteMatches.length); return; }
  if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); runPaletteCommand(paletteMatches[paletteIndex] ?? paletteMatches[0]); return; }
}
```
Extend the existing `Escape` block so Esc closes the palette first (before collapsing), exactly like `pickerOpen`:
```tsx
if (paletteOpen) { setPaletteOpen(false); return; }   // add alongside the pickerOpen Esc close
```
Add the runner (a small method near `confirmPickerSelection`):
```tsx
function runPaletteCommand(cmd: PaletteCommand | undefined) {
  if (!cmd) return;
  cmd.run();
  setInput('');
  setPaletteOpen(false);
  setPaletteIndex(0);
}
```
**4f. `handleSubmit` guard** — the NL-safety fallback so a `>` string is NEVER POSTed to `/api/chat`. Place it at
the **top of `handleSubmit`, immediately after `if (!text) return;`**, beside the `/grant` guard:
```tsx
// AD-946: '>' = command palette. Run the best match (or no-op); never submit as chat.
if (text.startsWith('>')) {
  const cmds = matchPaletteCommands(text.slice(1), paletteCommands);
  if (cmds.length > 0) (cmds[paletteIndex] ?? cmds[0]).run();   // honor the highlighted row
  setInput('');
  setPaletteOpen(false);
  setPaletteIndex(0);
  return;
}
```
*(The primary run path is Enter-in-`handleKeyDown`; this guard catches focus edge cases.)*

**4g. Render the dropdown** — beside the @-picker portal block (`:2031`), portal-anchored above the input the same
way (reuse `inputRef.current.getBoundingClientRect()` + `createPortal(…, document.body)`):
```tsx
{paletteOpen && inputRef.current && createPortal(
  (() => {
    const rect = inputRef.current!.getBoundingClientRect();
    return (
      <div style={{ position:'fixed', bottom: window.innerHeight - rect.top + 4, left: rect.left, width: rect.width, zIndex: 1000 }}>
        <CommandPalette
          matches={paletteMatches}
          activeIndex={paletteIndex}
          onHover={setPaletteIndex}
          onRun={runPaletteCommand}
        />
      </div>
    );
  })(),
  document.body,
)}
```
**4h.** Extend the existing `onBlur` / click-outside close so a click inside `[data-testid="command-palette"]`
does NOT collapse the shell (mirror the `at-picker-popover` allowance at `:142`), and the `onBlur` 150ms timeout
also `setPaletteOpen(false)`.

**Scroll-into-view** (HXI #4): add the jsdom-guarded effect mirroring the @-picker (`:425`–`:430`), keyed
`[paletteOpen, paletteIndex]`, querying `[data-cmd-index="${paletteIndex}"]`.

---

## Test plan

**Baseline:** AD-945 = **1344 passed / 1 skipped** (225 files). Expect **+N**, zero regressions.

### T1 — pure helpers: `ui/src/components/bridge/__tests__/paletteCommands.test.ts` (NEW)
Import the real `buildBridgeStations` (no mocks) + the two helpers.
- `buildPaletteCommands(buildBridgeStations({dmChannelCount:4,kanbanCount:7,totalUnread:3}))` returns **11**
  commands; the labels include `Ward Room, Chats, Crew, Personnel, Metrics, Notebooks, Records, Explorer, Work
  Board, System, Settings`.
- Communications contributes its **actions** (Ward Room + Chats), NOT a `communications:expand` (assert no command
  `id === 'communications:expand'` — the onExpand is skipped because the station has actions → **no duplicate Ward
  Room**).
- Operations → exactly one command `id === 'operations:expand'`, `label === 'Work Board'`; Engineering → one,
  `label === 'System'`.
- `config` excluded: assert no command labelled `Environment` and none labelled `Communications` (the comms-admin
  config).
- `matchPaletteCommands`: `'work'`→[Work Board]; `'ward'`→[Ward Room]; `'settings'`→[Settings]; `'chats'`→[Chats];
  `'science records'`→[Records]; `''`→[]; `'   '`→[]; `'xyzzy'`→[]; case-insensitive (`'WARD'`→[Ward Room]).
- run smoke: spy `useStore.setState`; the Work Board command's `.run()` calls `setState({ mainViewer: 'work' })`.

### T2 — component: `ui/src/__tests__/CommandPalette.test.tsx` (NEW)
Render `<CommandPalette matches={[…2 fixed cmds]} activeIndex={0} onHover onRun />` (props only, no store).
- `role="listbox"` present; two `role="option"` rows; row 0 `aria-selected="true"`, row 1 `false`.
- `onRun` called with the row's command on click (`onMouseDown`).
- A `ChevronRight` `<svg stroke=…>` is present in each row; **no-emoji guard** (regex
  `/[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}]/u` over `container.innerHTML` → none).
- Empty state: `matches={[]}` → "No matching command." rendered, no `option` rows.

### T3 — integration: `ui/src/__tests__/IntentSurface.commandPalette.test.tsx` (NEW)
Mirror the `IntentSurface.pickerKeyboard.test.tsx` harness (render `<IntentSurface/>`, open the shell via the pill,
`getInput()` by `input[placeholder="Ask ProbOS..."]`, seed the store via `setState`, stub `global.fetch`). Seed
`wardRoomDmChannels`, `missionControlTasks`, `wardRoomUnread` so the registry builds.
- **`>ward` → Enter runs the launch, not chat:** spy `useStore.getState().openWardRoom`; type `>ward`, press
  Enter → `openWardRoom` called **once**, `fetch` **NOT** called with `'/api/chat'`, `input` cleared, palette closed.
- **`>work` → Enter sets `mainViewer:'work'`** (assert `useStore.getState().mainViewer === 'work'`).
- **ArrowDown then Enter** runs the second match (spy the correct action).
- **Esc** closes the palette (`data-testid="command-palette"` gone) without collapsing on the first press.
- **NL guarantee (the regression guard):** type `what is the weather` (no `>`), press Enter → `addChatMessage('user',
  …)` ran and `fetch` **WAS** called with `'/api/chat'`; the palette **never** rendered (`queryByTestId('command-
  palette')` null throughout).
- **belt-and-suspenders:** type `>zzz` (no matches) → Enter → `fetch` NOT called with `'/api/chat'`, input cleared,
  no throw.

### T4 — registry guard: `ui/src/components/bridge/__tests__/stations.test.tsx` (UPDATE)
Add one case: `operations.onExpandLabel === 'Work Board'` and `engineering.onExpandLabel === 'System'`; the other
stations' `onExpandLabel` is `undefined`. (Do not disturb the existing AD-943/944 cases.)

### Gates
- `cd ui; npx vitest run` — green, **1344 + N**, zero regressions.
- `cd ui; npm run build` — clean (`tsc -b` + `vite`); watch the new `onExpandLabel?` field, the 3 new IntentSurface
  selectors, and no unused-import drift.
- `cd ui; npx playwright test` — **4 specs pass.** The e2e specs (`add-people`, `draggable-chats`,
  `meeting-avatars`, `group-chat-open`) **never touch the omnibox** (grep `Ask ProbOS`/`IntentSurface`/`intent-
  input` across `ui/e2e` → 0 matches); the palette only adds a leading-`>` branch and leaves the non-`>` NL submit
  byte-for-byte, so the e2e are unaffected.
- **No backend change → no pytest.**

---

## What this does NOT change (the fence)
- **The NL decomposition/submit path is untouched for any input not starting with `>`** — `handleSubmit`'s
  `addChatMessage` + `fetch('/api/chat')` path, the conversation-context slice, attachments, `/grant` — all
  byte-for-byte.
- **No second global key listener** — integrates with the existing `App.tsx` `triggerInput`/`pendingChar` seam.
- **The placeholder string stays `"Ask ProbOS..."`** (AD-719/941 selectors depend on it).
- **No `config` palette entries and no voice command of stations** — forward marker **AD-946a** (reuses
  `buildPaletteCommands` + `matchPaletteCommands`).
- **No hand-duplicated command list** — derived from `buildBridgeStations`.
- **The @-picker (`@<tail>`) is untouched** — palette (`>` lead) and picker (`@` tail) are exclusive triggers.
- **No Bridge station render change** — titles/accents/`defaultOpen`/`onExpand` targets/AD-944 actions/AD-945 config
  unchanged; `onExpandLabel` is additive and `BridgePanel` does not read it.
- **No new store state/flags/localStorage keys** (palette state is local to IntentSurface); **no backend/REST/pytest**;
  **no push.**

## Trackers (update after green)
- `DECISIONS.md` — prepend the AD-946 entry.
- `docs/development/roadmap.md` — AD-946 row; note AD-946a (voice + config palette) as the forward marker.
- `PROGRESS.md` — the banner line; mark the "Bridge as Ship's Computer" epic (#873) complete through AD-946.

## Acceptance criteria
1. Typing `>` in the omnibox opens a keyboard-navigable command dropdown derived from `buildBridgeStations`; the
   11 launches resolve; Enter/Tab runs the highlighted command's registry invoke; Arrow keys cycle; Esc closes;
   mouse hover/click work.
2. `>work`→Work Board, `>system`→System, `>ward`→Ward Room, `>settings`→Settings (and the rest) all run the same
   store action the Bridge fires.
3. A plain NL question (no `>`) submits **exactly as today** (`/api/chat`); the palette never opens for it. A `>`
   string is never POSTed to `/api/chat`.
4. `role="listbox"`/`role="option"`/`aria-selected`, stroke-SVG `ChevronRight`, amber active, **NO emoji**.
5. All three gates green (vitest 1344+N / build clean / 4 e2e pass); no pytest.
6. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Verified Against Codebase (2026-06-09)

```
grep -n "placeholder=\"Ask ProbOS" ui/src/components/IntentSurface.tsx
  2179: placeholder="Ask ProbOS..."
  2400: Ask ProbOS...
grep -n "function handleSubmit|startsWith('/grant|fetch('/api/chat'" ui/src/components/IntentSurface.tsx
  294: function handleSubmit(e: React.FormEvent)
  302:   if (text.startsWith('/grant ')) {        # only client-side leading-sigil guard → '>' is free
grep -n "function handleKeyDown|function handleInputChange|pickerOpen && pickerMatches" ui/src/components/IntentSurface.tsx
  433: function handleKeyDown(e: React.KeyboardEvent)
  454:   if (pickerOpen && pickerMatches.length > 0) {     # ↑/↓/Tab/Enter @-picker nav (mirror)
  514: function handleInputChange(value: string)
  2031: {pickerOpen && pickerMatches.length > 0 && inputRef.current && createPortal(   # portal anchor pattern
grep -n "consume pending char|triggerInput" ui/src/App.tsx ui/src/store/useStore.ts ui/src/components/IntentSurface.tsx
  App.tsx:51:        useStore.getState().triggerInput(e.key);
  useStore.ts:1613:  triggerInput: (char) => set({ pendingChar: char }),
  IntentSurface.tsx:106: if (pendingChar && !active) {   # Spotlight landing → seeds input
grep -n "buildBridgeStations|onExpand:|onExpandLabel" ui/src/components/bridge/stations.tsx
  68: export function buildBridgeStations(ctx: { dmChannelCount: number; kanbanCount: number; totalUnread: number })
  41:   onExpand?: () => void;     # CommandStation — onExpandLabel added here (Section 2a)
  (operations onExpand → mainViewer:'work' @ :136; engineering onExpand → mainViewer:'system' @ :155)
grep -n "buildBridgeStations\(\{|wardRoomDmChannels|missionControlTasks|wardRoomUnread|totalUnread" ui/src/components/BridgePanel.tsx
  107: const missionControlTasks = useStore(s => s.missionControlTasks);
  108: const dmChannels = useStore(s => s.wardRoomDmChannels);
  110: const wardRoomUnread = useStore(s => s.wardRoomUnread);
  111: const totalUnread = Object.values(wardRoomUnread ?? {}).reduce((sum, n) => sum + n, 0);
  217: {buildBridgeStations({ dmChannelCount: dmChannels.length, kanbanCount: kanbanTasks.length, totalUnread })
grep -n "openWardRoom|openChats|openCrewManifest|openSpatialExplorer" ui/src/store/useStore.ts
  1087: openChats: () => set({ chatsOpen: true }),
  1204: openSpatialExplorer: () => set({ spatialExplorerOpen: true }),
  1389: openWardRoom: async (channelId?: string) => { …   # all action closures are pure global getState/setState
  useSettingsStore.ts:134: openSettings: async () => { …
grep -n "export const ChevronRight" ui/src/components/icons/Glyphs.tsx
  30: export const ChevronRight: React.FC<GlyphProps> = …   # reuse for the palette rows
grep -n "handleKeyDown|scrollIntoView|role=" ui/src/components/profile/AddParticipantPopover.tsx
  91: function handleKeyDown(e: React.KeyboardEvent)   # ↑/↓/Enter/Tab/Esc + index-reset (mirror)
  83: if (el && typeof el.scrollIntoView === 'function')   # jsdom guard (mirror)
grep -rn "Ask ProbOS|IntentSurface|intent-input" ui/e2e/
  (0 matches — the 4 e2e specs never touch the omnibox → unaffected)
grep -rn "palette|CommandPalette|slashCommand" ui/src/
  (0 matches — no existing palette UI; clean build)
IntentSurface test harness precedent: ui/src/__tests__/IntentSurface.pickerKeyboard.test.tsx (render + openShell + getInput by placeholder)
registry test to extend: ui/src/components/bridge/__tests__/stations.test.tsx
```
