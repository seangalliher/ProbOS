/**
 * AD-705c (Wave 179) — WakeWordTrainerPanel vitest.
 *
 * BF-287: real useSettingsStore; fetch + MediaRecorder stubbed at the
 * global boundary.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, fireEvent, waitFor, cleanup } from '@testing-library/react';

import { WakeWordTrainerPanel } from '../WakeWordTrainerPanel';
import { useSettingsStore } from '../../../store/useSettingsStore';

function setSnapshot(enabled: boolean): void {
  useSettingsStore.setState({
    snapshot: enabled
      ? ({
          config: { wake_word: { wake_word_trainer_enabled: true } },
          sections: [],
          domain_counts: {},
          domain_order: [],
          section_count: 0,
          config_path: '',
          uptime_seconds: 0,
          csrf_token: '',
          secret_present: {},
        } as any)
      : null,
  });
}

beforeEach(() => {
  setSnapshot(false);
  (globalThis as any).fetch = vi.fn();
});

afterEach(() => {
  vi.restoreAllMocks();
  cleanup();
});

describe('WakeWordTrainerPanel', () => {
  it('renders when wake_word_trainer_enabled=true', () => {
    setSnapshot(true);
    const { getByTestId } = render(<WakeWordTrainerPanel recommendedSamples={3} />);
    expect(getByTestId('wake-word-trainer-panel')).toBeTruthy();
  });

  it('does NOT render when wake_word_trainer_enabled=false', () => {
    setSnapshot(false);
    const { queryByTestId } = render(<WakeWordTrainerPanel />);
    expect(queryByTestId('wake-word-trainer-panel')).toBeNull();
  });

  it('clicking record uploads a sample and increments the counter', async () => {
    setSnapshot(true);
    (globalThis as any).fetch = vi.fn(async (url: string) => {
      if (typeof url === 'string' && url.endsWith('/sample')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({ stored: true, samples_count: 1 }),
        } as Response;
      }
      return { ok: false, status: 404 } as Response;
    });
    const { getByTestId } = render(<WakeWordTrainerPanel recommendedSamples={3} />);
    const recordButton = getByTestId('wake-word-record-button');
    fireEvent.click(recordButton);
    await waitFor(() => {
      expect(getByTestId('wake-word-progress').textContent).toContain('1 / 3');
    });
    expect((globalThis as any).fetch).toHaveBeenCalledWith(
      '/api/voice/wake-word/sample',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('train button posts to /train and polls /training-status until complete', async () => {
    setSnapshot(true);
    let pollCount = 0;
    (globalThis as any).fetch = vi.fn(async (url: string, opts?: RequestInit) => {
      const u = typeof url === 'string' ? url : '';
      if (u.endsWith('/sample')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({ samples_count: 1 }),
        } as Response;
      }
      if (u.endsWith('/train') && opts?.method === 'POST') {
        return {
          ok: true,
          status: 200,
          json: async () => ({ job_id: 'job-99', status: 'started' }),
        } as Response;
      }
      if (u.includes('/training-status')) {
        pollCount += 1;
        return {
          ok: true,
          status: 200,
          json: async () => ({
            status: 'complete',
            progress: 1.0,
            model_path: '/models/wake-word/captain.onnx',
          }),
        } as Response;
      }
      return { ok: false, status: 404 } as Response;
    });
    // Pre-seed the progress so the train button renders immediately.
    const { getByTestId, queryByTestId } = render(
      <WakeWordTrainerPanel recommendedSamples={1} />,
    );
    fireEvent.click(getByTestId('wake-word-record-button'));
    await waitFor(() => {
      expect(getByTestId('wake-word-progress').textContent).toContain('1 / 1');
    });
    // Train button now visible.
    const trainButton = await waitFor(() => getByTestId('wake-word-train-button'));
    fireEvent.click(trainButton);
    await waitFor(() => {
      expect(queryByTestId('wake-word-complete')).toBeTruthy();
    });
    expect(pollCount).toBeGreaterThanOrEqual(1);
  });
});
