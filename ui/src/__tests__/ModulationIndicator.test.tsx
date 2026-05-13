// AD-718d-1: ModulationIndicator pulses on speech events for the right agent.

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup, act } from '@testing-library/react';
import { ModulationIndicator } from '../components/profile/ModulationIndicator';
import * as voice from '../audio/voice';

let listener: ((evt: voice.SpeechEvent) => void) | null = null;
const unsub = vi.fn();

beforeEach(() => {
  listener = null;
  unsub.mockClear();
  vi.spyOn(voice, 'onSpeechEvent').mockImplementation((fn) => {
    listener = fn;
    return unsub;
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function fire(evt: voice.SpeechEvent) {
  if (!listener) throw new Error('listener not registered');
  act(() => listener!(evt));
}

describe('ModulationIndicator', () => {
  it('pulses while speech is active for the agent', () => {
    render(<ModulationIndicator agentId="agent-1" />);
    const node = screen.getByTestId('modulation-indicator');
    expect(node.getAttribute('data-active')).toBe('false');
    fire({ type: 'start', agent_id: 'agent-1', utterance: {} as SpeechSynthesisUtterance });
    expect(node.getAttribute('data-active')).toBe('true');
    fire({ type: 'end', agent_id: 'agent-1', utterance: {} as SpeechSynthesisUtterance });
    expect(node.getAttribute('data-active')).toBe('false');
  });

  it('ignores events for other agents', () => {
    render(<ModulationIndicator agentId="agent-1" />);
    const node = screen.getByTestId('modulation-indicator');
    fire({ type: 'start', agent_id: 'agent-2', utterance: {} as SpeechSynthesisUtterance });
    expect(node.getAttribute('data-active')).toBe('false');
  });
});
