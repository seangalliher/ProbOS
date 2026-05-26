/** AD-792 (Wave 195) vitest — timeOfLifeGroup buckets last_active_at
 * timestamps correctly into Today / Yesterday / Earlier relative to
 * local midnight. Pure function — no DOM needed. */
import { describe, it, expect } from 'vitest';
import { timeOfLifeGroup, TIME_OF_LIFE_LABELS } from '../components/sidebar/threadGrouping';

describe('threadGrouping.timeOfLifeGroup', () => {
  // Reference: 2026-05-25 12:00:00 local time.
  const NOW = new Date(2026, 4, 25, 12, 0, 0, 0).getTime();
  const DAY_MS = 86_400_000;

  it('buckets a same-day timestamp as today', () => {
    const sec = new Date(2026, 4, 25, 9, 0, 0, 0).getTime() / 1000;
    expect(timeOfLifeGroup(sec, NOW)).toBe('today');
  });

  it('buckets a midnight-anchored timestamp as today', () => {
    const sec = new Date(2026, 4, 25, 0, 0, 0, 0).getTime() / 1000;
    expect(timeOfLifeGroup(sec, NOW)).toBe('today');
  });

  it('buckets a yesterday timestamp as yesterday', () => {
    const sec = new Date(2026, 4, 24, 15, 0, 0, 0).getTime() / 1000;
    expect(timeOfLifeGroup(sec, NOW)).toBe('yesterday');
  });

  it('buckets a 2-day-old timestamp as earlier', () => {
    const sec = (NOW - 2 * DAY_MS) / 1000;
    expect(timeOfLifeGroup(sec, NOW)).toBe('earlier');
  });

  it('buckets a far-past timestamp as earlier', () => {
    const sec = (NOW - 30 * DAY_MS) / 1000;
    expect(timeOfLifeGroup(sec, NOW)).toBe('earlier');
  });

  it('exposes human labels for each group', () => {
    expect(TIME_OF_LIFE_LABELS.today).toBe('Today');
    expect(TIME_OF_LIFE_LABELS.yesterday).toBe('Yesterday');
    expect(TIME_OF_LIFE_LABELS.earlier).toBe('Earlier');
  });
});
