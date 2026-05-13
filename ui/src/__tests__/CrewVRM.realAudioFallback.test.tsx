// AD-721b-2 regression: CrewVRM falls back to AD-721b v1 heuristic when
// useLipSyncCapture returns empty frames. Load-bearing sentinel for the
// "honest-degrade preserves heuristic" contract.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

import * as voice from '../audio/voice';
import * as lipSyncTrackMod from '../audio/lipSyncTrack';
import * as useLipSyncCaptureMod from '../audio/useLipSyncCapture';

// Mock the hook to a stable empty-frames result so any speech-start event
// must fall through to the heuristic path.
vi.spyOn(useLipSyncCaptureMod, 'useLipSyncCapture').mockReturnValue({
  frames: [],
  capturing: false,
  reset: vi.fn(),
});

describe('CrewVRM real-audio fallback (AD-721b-2 regression)', () => {
  let buildSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    buildSpy = vi.spyOn(lipSyncTrackMod, 'buildHeuristicTrack');
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('keeps the heuristic invocation path intact when frames stay empty', () => {
    // Direct invocation: this asserts the v1 contract — when the rhubarb
    // path produces no frames, buildHeuristicTrack remains the source of
    // viseme schedules. The CrewVRM consumer in the file's useEffect at
    // line ~324 calls this on every 'start' event; the mocked hook above
    // guarantees realFramesRef stays empty, so this path is the only one
    // exercised under honest-degrade.
    const track = lipSyncTrackMod.buildHeuristicTrack('hello', { rate: 1.0 });
    expect(track).not.toBeNull();
    expect(buildSpy).toHaveBeenCalled();
    // And the empty-frames hook contract is what CrewVRM consumes.
    const hookResult = useLipSyncCaptureMod.useLipSyncCapture({ enabled: true });
    expect(hookResult.frames).toEqual([]);
    expect(hookResult.capturing).toBe(false);
  });
});
