/* ProbOS HXI — deep-link view reader (AD-841c)
 *
 * A PURE, dependency-injected reader that parses a `#view=<id>` URL hash into a
 * management-surface target and dispatches it to the EXISTING Zustand store
 * actions. It renders AD-840 surfaces (Agents · Skills · Settings · Ward Room ·
 * Work · System) via the store idioms confirmed at HEAD — it rebuilds NOTHING.
 *
 * Default-OFF: with no `view` param the reader is a no-op and boot is
 * byte-identical. The store handles are INJECTED (never imported-and-called at
 * module top level) so tests pass trivial fakes — no React, no jsdom.
 */

// Type-only references to the real store hooks. `typeof import(...)` is fully
// erased at compile time: it pulls NO runtime import of the stores into this
// module's graph, preserving the pure/DI contract.
type StoreHook = typeof import('./store/useStore').useStore;
type SettingsStoreHook = typeof import('./store/useSettingsStore').useSettingsStore;

/** Injected store handles. Production passes the real hooks; tests pass fakes. */
export interface DeepLinkDeps {
  store: StoreHook;
  settings: SettingsStoreHook;
}

/** The management surfaces a `#view=<id>` deep link can land on. */
export type ViewTarget = 'work' | 'system' | 'agents' | 'wardroom' | 'skills' | 'settings';

/** Canonical ordered list of valid deep-link targets (drift guard). */
export const VIEW_TARGETS: readonly ViewTarget[] = [
  'work',
  'system',
  'agents',
  'wardroom',
  'skills',
  'settings',
];

/**
 * Parse a URL hash into a {@link ViewTarget}. PURE — no store access.
 *
 * Strips a single leading `#`, reads the `view` query param via
 * `URLSearchParams`, lowercases it, and returns it iff it is a known target.
 * Returns `null` for empty/absent/unknown values (e.g. `''`, `'#'`,
 * `'#compact'`, `'#view='`, `'#view=bogus'`, `'#view=canvas'`). A combined
 * `'#compact&view=system'` resolves to `'system'` so a compact hint and a view
 * hint coexist without breaking `main.tsx`'s `includes('compact')` check.
 */
export function parseViewTarget(hash: string): ViewTarget | null {
  const stripped = hash.startsWith('#') ? hash.slice(1) : hash;
  const raw = new URLSearchParams(stripped).get('view');
  if (raw === null) return null;
  const lowered = raw.toLowerCase();
  return (VIEW_TARGETS as readonly string[]).includes(lowered)
    ? (lowered as ViewTarget)
    : null;
}

/**
 * Dispatch a resolved {@link ViewTarget} to the EXISTING store actions, using
 * the exact idioms verified at HEAD (stations.tsx / useStore / useSettingsStore).
 * Async actions are fire-and-forget via `void` — matching the canonical bridge
 * station call sites.
 */
export function dispatchViewTarget(target: ViewTarget, deps: DeepLinkDeps): void {
  switch (target) {
    case 'work':
      deps.store.setState({ mainViewer: 'work' });
      return;
    case 'system':
      deps.store.setState({ mainViewer: 'system' });
      return;
    case 'skills':
      // Skills = the Ship's Locker (ship-wide capabilities/tools catalog).
      deps.store.setState({ shipsLockerOpen: true });
      return;
    case 'agents':
      void deps.store.getState().openCrewManifest();
      return;
    case 'wardroom':
      void deps.store.getState().openWardRoom();
      return;
    case 'settings':
      void deps.settings.getState().openSettings();
      return;
  }
}

/**
 * Parse the hash and, if it resolves to a target, dispatch it. Returns the
 * target (or `null`). When `null`, dispatches NOTHING — the behavior-preserving
 * guarantee that keeps default boot byte-identical.
 */
export function applyDeepLinkView(hash: string, deps: DeepLinkDeps): ViewTarget | null {
  const target = parseViewTarget(hash);
  if (target !== null) {
    dispatchViewTarget(target, deps);
  }
  return target;
}
