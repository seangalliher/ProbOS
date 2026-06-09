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
 *  Empty/whitespace query → ALL commands, so a bare '>' lists every launch
 *  (AD-946b). Command mode is gated by the leading '>' at the call site, not by
 *  the query content, so returning the full list here is safe. */
export function matchPaletteCommands(
  query: string,
  commands: PaletteCommand[],
): PaletteCommand[] {
  const q = query.trim().toLowerCase();
  if (!q) return commands.slice();
  const terms = q.split(/\s+/);
  return commands.filter((c) => {
    const hay = `${c.station} ${c.label}`.toLowerCase();
    return terms.every((t) => hay.includes(t));
  });
}
