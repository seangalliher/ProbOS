/**
 * AD-562: Knowledge Browser shared color tokens (lifted from NotebooksPanel).
 *
 * Single source of truth across record surfaces.
 */
export const DEPT_COLORS: Record<string, string> = {
  engineering: '#b0a050',
  science: '#50b0a0',
  medical: '#5090d0',
  security: '#d05050',
  bridge: '#d0a030',
};

export const CLASS_COLORS: Record<string, string> = {
  private: '#7060a8',
  department: '#88a4c8',
  ship: '#f0b060',
  fleet: '#e0c070',
};

export function deptColor(dept: string): string {
  return DEPT_COLORS[(dept || '').toLowerCase()] || '#8888a0';
}

export function classColor(cls: string): string {
  return CLASS_COLORS[(cls || '').toLowerCase()] || '#8888a0';
}
