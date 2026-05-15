// AD-722b-4a: store action tests for fleet telemetry frame ingestion.

import { describe, expect, beforeEach, test } from 'vitest';
import { useStore } from '../store/useStore';

describe('useStore.setAvatarTelemetryFrame', () => {
  beforeEach(() => {
    useStore.setState({ avatarTelemetry: new Map() });
  });

  test('snapshot replaces entry', () => {
    const { setAvatarTelemetryFrame } = useStore.getState();

    setAvatarTelemetryFrame('a1', 'snapshot', { emotion: 'calm' });
    expect(useStore.getState().avatarTelemetry.get('a1')).toEqual({ emotion: 'calm' });

    setAvatarTelemetryFrame('a1', 'snapshot', { emotion: 'focused', working_state: 'thinking' });
    expect(useStore.getState().avatarTelemetry.get('a1')).toEqual({
      emotion: 'focused',
      working_state: 'thinking',
    });
  });

  test('diff before snapshot is dropped', () => {
    const { setAvatarTelemetryFrame } = useStore.getState();
    setAvatarTelemetryFrame('a2', 'diff', { working_state: 'thinking' });
    expect(useStore.getState().avatarTelemetry.get('a2')).toBeUndefined();
  });

  test('diff after snapshot shallow-merges', () => {
    const { setAvatarTelemetryFrame } = useStore.getState();
    setAvatarTelemetryFrame('a3', 'snapshot', { emotion: 'calm', working_state: 'idle' });
    setAvatarTelemetryFrame('a3', 'diff', { working_state: 'thinking' });
    expect(useStore.getState().avatarTelemetry.get('a3')).toEqual({
      emotion: 'calm',
      working_state: 'thinking',
    });
  });
});
