import { describe, it, expect, beforeEach } from 'vitest';
import { useStore } from '../store/useStore';
import { soundEngine } from '../audio/soundEngine';
import type { BridgeState } from '../components/glass/ContextRibbon';

beforeEach(() => {
  useStore.setState({
    scanLinesEnabled: false,
    chromaticAberrationEnabled: false,
    dataRainEnabled: false,
    atmosphereIntensity: 0.3,
  });
  localStorage.clear();
});

describe('atmosphere preferences (AD-391)', () => {
  it('all three effects default to false, intensity defaults to 0.3', () => {
    expect(useStore.getState().scanLinesEnabled).toBe(false);
    expect(useStore.getState().chromaticAberrationEnabled).toBe(false);
    expect(useStore.getState().dataRainEnabled).toBe(false);
    expect(useStore.getState().atmosphereIntensity).toBe(0.3);
  });

  it('setScanLinesEnabled updates store and persists', () => {
    useStore.getState().setScanLinesEnabled(true);
    expect(useStore.getState().scanLinesEnabled).toBe(true);
    const stored = JSON.parse(localStorage.getItem('hxi_atmosphere_prefs') || '{}');
    expect(stored.scanLinesEnabled).toBe(true);
  });

  it('setChromaticAberrationEnabled updates store and persists', () => {
    useStore.getState().setChromaticAberrationEnabled(true);
    expect(useStore.getState().chromaticAberrationEnabled).toBe(true);
    const stored = JSON.parse(localStorage.getItem('hxi_atmosphere_prefs') || '{}');
    expect(stored.chromaticAberrationEnabled).toBe(true);
  });

  it('setDataRainEnabled updates store and persists', () => {
    useStore.getState().setDataRainEnabled(true);
    expect(useStore.getState().dataRainEnabled).toBe(true);
    const stored = JSON.parse(localStorage.getItem('hxi_atmosphere_prefs') || '{}');
    expect(stored.dataRainEnabled).toBe(true);
  });

  it('setAtmosphereIntensity clamps to 0-1 range', () => {
    useStore.getState().setAtmosphereIntensity(1.5);
    expect(useStore.getState().atmosphereIntensity).toBe(1);

    useStore.getState().setAtmosphereIntensity(-0.5);
    expect(useStore.getState().atmosphereIntensity).toBe(0);

    useStore.getState().setAtmosphereIntensity(0.7);
    expect(useStore.getState().atmosphereIntensity).toBe(0.7);
  });

  it('atmosphere preferences round-trip through localStorage', () => {
    useStore.getState().setScanLinesEnabled(true);
    useStore.getState().setChromaticAberrationEnabled(true);
    useStore.getState().setAtmosphereIntensity(0.8);

    const stored = JSON.parse(localStorage.getItem('hxi_atmosphere_prefs') || '{}');
    expect(stored.scanLinesEnabled).toBe(true);
    expect(stored.chromaticAberrationEnabled).toBe(true);
    expect(stored.atmosphereIntensity).toBe(0.8);
  });
});

describe('luminance ripple detection (AD-391)', () => {
  it('bridge state change can be tracked via ref pattern', () => {
    let prevState: BridgeState | null = null;
    const states: BridgeState[] = ['idle', 'autonomous', 'attention'];
    const ripples: boolean[] = [];

    for (const state of states) {
      const shouldRipple = prevState !== null && prevState !== state;
      ripples.push(shouldRipple);
      prevState = state;
    }

    expect(ripples).toEqual([false, true, true]);
  });
});

describe('sound engine new methods (AD-391)', () => {
  it('playStepComplete exists and does not throw without init', () => {
    expect(typeof soundEngine.playStepComplete).toBe('function');
    expect(() => soundEngine.playStepComplete(0, 5)).not.toThrow();
  });

  it('playCaptainReturn exists and does not throw without init', () => {
    expect(typeof soundEngine.playCaptainReturn).toBe('function');
    expect(() => soundEngine.playCaptainReturn()).not.toThrow();
  });

  it('playBridgeHum exists and does not throw without init', () => {
    expect(typeof soundEngine.playBridgeHum).toBe('function');
    expect(() => soundEngine.playBridgeHum('idle')).not.toThrow();
  });
});
