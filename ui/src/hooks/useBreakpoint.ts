/* useBreakpoint — viewport width breakpoint detection (AD-392) */

import { useState, useEffect } from 'react';

export type Breakpoint = 'ultrawide' | 'standard' | 'laptop' | 'tablet' | 'mobile';

export function getBreakpoint(): Breakpoint {
  const w = window.innerWidth;
  if (w > 2560) return 'ultrawide';
  if (w > 1440) return 'standard';
  if (w > 1024) return 'laptop';
  if (w > 768) return 'tablet';
  return 'mobile';
}

export function useBreakpoint(): Breakpoint {
  const [bp, setBp] = useState<Breakpoint>(getBreakpoint());

  useEffect(() => {
    const handler = () => setBp(getBreakpoint());
    window.addEventListener('resize', handler);
    return () => window.removeEventListener('resize', handler);
  }, []);

  return bp;
}
