/* AD-946: the Ship's-Computer command palette — a pure, props-driven dropdown
 * the omnibox (IntentSurface) renders above the input when the Captain types a
 * leading '>'. Nav state (the active row) lives on the host, like the AD-719
 * @-picker; this component only renders + reports hover/run. Rows mirror
 * AddParticipantPopover's a11y/amber palette. HXI #3 — stroke-SVG glyphs, no
 * emoji. */
import { ChevronRight } from './icons/Glyphs';
import type { PaletteCommand } from './bridge/paletteCommands';

interface CommandPaletteProps {
  matches: PaletteCommand[];
  activeIndex: number;
  onHover: (i: number) => void;
  onRun: (cmd: PaletteCommand) => void;
}

export function CommandPalette({ matches, activeIndex, onHover, onRun }: CommandPaletteProps) {
  return (
    <div
      role="listbox"
      aria-label="Bridge commands"
      data-testid="command-palette"
      style={{
        maxHeight: 240,
        overflowY: 'auto',
        background: 'rgba(10, 10, 18, 0.96)',
        border: '1px solid rgba(240, 176, 96, 0.25)',
        borderRadius: 8,
        backdropFilter: 'blur(12px)',
        WebkitBackdropFilter: 'blur(12px)',
        boxShadow: '0 4px 16px rgba(0,0,0,0.4)',
        pointerEvents: 'auto',
      }}
    >
      {matches.length === 0 && (
        <div style={{ color: '#666680', fontSize: 11, padding: '6px 12px' }}>
          No matching command.
        </div>
      )}
      {matches.map((cmd, i) => {
        const isActive = i === activeIndex;
        return (
          <div
            key={cmd.id}
            role="option"
            aria-selected={isActive}
            data-testid="command-palette-row"
            data-cmd-index={i}
            // Mouse-confirm without stealing input focus (mirror the @-picker).
            onMouseDown={(e) => { e.preventDefault(); onRun(cmd); }}
            onMouseEnter={() => onHover(i)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              padding: '6px 12px',
              cursor: 'pointer',
              fontSize: 13,
              // Amber wash for the active row; transparent otherwise (HXI #4).
              background: isActive ? 'rgba(240,176,96,0.12)' : 'transparent',
            }}
          >
            <ChevronRight size={12} style={{ color: isActive ? '#f0b060' : '#666680', flexShrink: 0 }} />
            <span style={{ color: isActive ? '#f0b060' : '#e0dcd4', fontWeight: 500 }}>{cmd.label}</span>
            <span style={{
              marginLeft: 'auto',
              fontSize: 10,
              color: '#666680',
              textTransform: 'uppercase',
              letterSpacing: 0.5,
            }}>{cmd.station}</span>
          </div>
        );
      })}
    </div>
  );
}
