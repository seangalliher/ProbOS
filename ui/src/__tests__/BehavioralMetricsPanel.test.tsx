/**
 * AD-569g: HXI Behavioral Metrics Dashboard tests.
 * Mirrors NotebooksPanel.test.tsx mocking pattern.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, act, cleanup, waitFor } from '@testing-library/react';
import BehavioralMetricsPanel from '../components/BehavioralMetricsPanel';
import { useStore } from '../store/useStore';

function resetStore() {
  useStore.setState({
    behavioralMetricsOpen: false,
    behavioralMetricsLoading: false,
    behavioralMetricsLatest: null,
    behavioralMetricsHistory: [],
    behavioralMetricsError: null,
  });
}

function jsonResp(body: any, ok = true): Response {
  return {
    ok,
    json: async () => body,
  } as unknown as Response;
}

function makeSnapshot(overrides: Partial<any> = {}): any {
  return {
    timestamp: 1_700_000_000,
    frame_diversity_score: 0.7,
    frame_diversity_threads: 4,
    department_representation: { engineering: 2, science: 3 },
    synthesis_rate: 0.5,
    synthesis_threads: 3,
    total_novel_elements: 9,
    cross_dept_trigger_rate: 0.3,
    trigger_pairs: [],
    trigger_events: 1,
    convergence_events: 2,
    verified_correct: 1,
    verified_incorrect: 0,
    unverified: 1,
    convergence_correctness_rate: 0.8,
    anchor_grounded_rate: 0.6,
    anchor_independence_score: 0.7,
    anchor_analyzed_threads: 3,
    threads_analyzed: 5,
    behavioral_quality_score: 0.65,
    ...overrides,
  };
}

describe('BehavioralMetricsPanel (AD-569g)', () => {
  beforeEach(() => {
    resetStore();
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    resetStore();
  });

  it('renders nothing when behavioralMetricsOpen is false', () => {
    render(<BehavioralMetricsPanel />);
    expect(screen.queryByTestId('behavioral-metrics-panel')).toBeNull();
  });

  it('opens and fetches both endpoints', async () => {
    const fetchMock = vi.spyOn(global, 'fetch').mockImplementation((url: any) => {
      if (typeof url === 'string' && url.includes('/history')) {
        return Promise.resolve(jsonResp({ snapshots: [] }));
      }
      return Promise.resolve(jsonResp(makeSnapshot()));
    });
    render(<BehavioralMetricsPanel />);
    await act(async () => {
      await useStore.getState().openBehavioralMetrics();
    });
    expect(fetchMock).toHaveBeenCalledWith('/api/behavioral-metrics');
    expect(fetchMock).toHaveBeenCalledWith('/api/behavioral-metrics/history?limit=20');
    expect(screen.getByTestId('behavioral-metrics-panel')).toBeTruthy();
  });

  it('renders all five metric tiles when data is present', async () => {
    vi.spyOn(global, 'fetch').mockImplementation((url: any) => {
      if (typeof url === 'string' && url.includes('/history')) {
        return Promise.resolve(jsonResp({ snapshots: [] }));
      }
      return Promise.resolve(jsonResp(makeSnapshot()));
    });
    render(<BehavioralMetricsPanel />);
    await act(async () => {
      await useStore.getState().openBehavioralMetrics();
    });
    expect(screen.getByTestId('behavioral-tile-frame_diversity_score')).toBeTruthy();
    expect(screen.getByTestId('behavioral-tile-synthesis_rate')).toBeTruthy();
    expect(screen.getByTestId('behavioral-tile-cross_dept_trigger_rate')).toBeTruthy();
    expect(screen.getByTestId('behavioral-tile-convergence_correctness_rate')).toBeTruthy();
    expect(screen.getByTestId('behavioral-tile-anchor_grounded_rate')).toBeTruthy();
    // Labels
    expect(screen.getByText('Frame Diversity')).toBeTruthy();
    expect(screen.getByText('Synthesis')).toBeTruthy();
    expect(screen.getByText('Cross-Dept Trigger')).toBeTruthy();
    expect(screen.getByText('Convergence Correctness')).toBeTruthy();
    expect(screen.getByText('Anchor-Grounded Emergence')).toBeTruthy();
  });

  it('renders composite quality score in the header', async () => {
    vi.spyOn(global, 'fetch').mockImplementation((url: any) => {
      if (typeof url === 'string' && url.includes('/history')) {
        return Promise.resolve(jsonResp({ snapshots: [] }));
      }
      return Promise.resolve(jsonResp(makeSnapshot({ behavioral_quality_score: 0.42 })));
    });
    render(<BehavioralMetricsPanel />);
    await act(async () => {
      await useStore.getState().openBehavioralMetrics();
    });
    const composite = screen.getByTestId('behavioral-metrics-composite');
    expect(composite.textContent).toContain('42%');
  });

  it('renders empty state when latest endpoint reports not_available', async () => {
    vi.spyOn(global, 'fetch').mockImplementation((url: any) => {
      if (typeof url === 'string' && url.includes('/history')) {
        return Promise.resolve(jsonResp({ snapshots: [] }));
      }
      return Promise.resolve(jsonResp({ status: 'not_available' }));
    });
    render(<BehavioralMetricsPanel />);
    await act(async () => {
      await useStore.getState().openBehavioralMetrics();
    });
    const empty = screen.getByTestId('behavioral-metrics-empty');
    expect(empty.textContent).toContain('after the first dream cycle');
  });

  it('renders empty state when latest endpoint reports no_data', async () => {
    vi.spyOn(global, 'fetch').mockImplementation((url: any) => {
      if (typeof url === 'string' && url.includes('/history')) {
        return Promise.resolve(jsonResp({ snapshots: [] }));
      }
      return Promise.resolve(jsonResp({ status: 'no_data' }));
    });
    render(<BehavioralMetricsPanel />);
    await act(async () => {
      await useStore.getState().openBehavioralMetrics();
    });
    expect(screen.getByTestId('behavioral-metrics-empty')).toBeTruthy();
  });

  it('renders em-dash for null convergence_correctness_rate', async () => {
    vi.spyOn(global, 'fetch').mockImplementation((url: any) => {
      if (typeof url === 'string' && url.includes('/history')) {
        return Promise.resolve(jsonResp({ snapshots: [] }));
      }
      return Promise.resolve(jsonResp(makeSnapshot({ convergence_correctness_rate: null })));
    });
    render(<BehavioralMetricsPanel />);
    await act(async () => {
      await useStore.getState().openBehavioralMetrics();
    });
    const score = screen.getByTestId('behavioral-score-convergence_correctness_rate');
    expect(score.textContent).toBe('—');
    // Other tiles still show numeric
    const frameScore = screen.getByTestId('behavioral-score-frame_diversity_score');
    expect(frameScore.textContent).toBe('0.70');
  });

  it('close button closes the panel', async () => {
    vi.spyOn(global, 'fetch').mockImplementation((url: any) => {
      if (typeof url === 'string' && url.includes('/history')) {
        return Promise.resolve(jsonResp({ snapshots: [] }));
      }
      return Promise.resolve(jsonResp(makeSnapshot()));
    });
    render(<BehavioralMetricsPanel />);
    await act(async () => {
      await useStore.getState().openBehavioralMetrics();
    });
    expect(useStore.getState().behavioralMetricsOpen).toBe(true);
    await act(async () => {
      fireEvent.click(screen.getByTestId('behavioral-metrics-close'));
    });
    expect(useStore.getState().behavioralMetricsOpen).toBe(false);
  });

  it('renders error state when fetch rejects', async () => {
    vi.spyOn(global, 'fetch').mockRejectedValue(new Error('network down'));
    render(<BehavioralMetricsPanel />);
    await act(async () => {
      await useStore.getState().openBehavioralMetrics();
    });
    const err = screen.getByTestId('behavioral-metrics-error');
    expect(err.textContent).toContain('network down');
  });

  it('renders sparkline polyline when history has 3+ entries', async () => {
    const history = [
      makeSnapshot({ timestamp: 1, frame_diversity_score: 0.2 }),
      makeSnapshot({ timestamp: 2, frame_diversity_score: 0.5 }),
      makeSnapshot({ timestamp: 3, frame_diversity_score: 0.8 }),
    ];
    vi.spyOn(global, 'fetch').mockImplementation((url: any) => {
      if (typeof url === 'string' && url.includes('/history')) {
        return Promise.resolve(jsonResp({ snapshots: history }));
      }
      return Promise.resolve(jsonResp(makeSnapshot()));
    });
    render(<BehavioralMetricsPanel />);
    await act(async () => {
      await useStore.getState().openBehavioralMetrics();
    });
    const sparkline = screen.getByTestId('behavioral-sparkline-frame_diversity_score');
    expect(sparkline.querySelector('polyline')).not.toBeNull();
  });

  it('renders dashed baseline when history is empty', async () => {
    vi.spyOn(global, 'fetch').mockImplementation((url: any) => {
      if (typeof url === 'string' && url.includes('/history')) {
        return Promise.resolve(jsonResp({ snapshots: [] }));
      }
      return Promise.resolve(jsonResp(makeSnapshot()));
    });
    render(<BehavioralMetricsPanel />);
    await act(async () => {
      await useStore.getState().openBehavioralMetrics();
    });
    const sparkline = screen.getByTestId('behavioral-sparkline-frame_diversity_score');
    const path = sparkline.querySelector('path');
    expect(path).not.toBeNull();
    expect(path!.getAttribute('stroke-dasharray')).toBeTruthy();
    expect(sparkline.querySelector('polyline')).toBeNull();
  });

  it('refresh button re-invokes fetch endpoints', async () => {
    const fetchMock = vi.spyOn(global, 'fetch').mockImplementation((url: any) => {
      if (typeof url === 'string' && url.includes('/history')) {
        return Promise.resolve(jsonResp({ snapshots: [] }));
      }
      return Promise.resolve(jsonResp(makeSnapshot()));
    });
    render(<BehavioralMetricsPanel />);
    await act(async () => {
      await useStore.getState().openBehavioralMetrics();
    });
    const callsBefore = fetchMock.mock.calls.length;
    await act(async () => {
      fireEvent.click(screen.getByTestId('behavioral-metrics-refresh'));
      await waitFor(() => {
        expect(fetchMock.mock.calls.length).toBeGreaterThan(callsBefore);
      });
    });
    expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(callsBefore + 2);
  });
});
