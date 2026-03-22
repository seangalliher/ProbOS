/* SoundEngine — procedural ambient sounds via Web Audio API (zero dependencies) */

class SoundEngine {
  private ctx: AudioContext | null = null;
  private masterGain: GainNode | null = null;
  private _muted: boolean = true; // OFF by default
  private _volume: number = 0.3;
  private _connected: boolean = true;
  private heartbeatInterval: ReturnType<typeof setInterval> | null = null;
  private dreamDrone: OscillatorNode | null = null;
  private dreamNoise: AudioBufferSourceNode | null = null;
  private bridgeHumOscs: OscillatorNode[] = [];
  private bridgeHumGains: GainNode[] = [];

  get initialized(): boolean { return this.ctx !== null; }
  get muted(): boolean { return this._muted; }
  get volume(): number { return this._volume; }

  /** Initialize AudioContext — MUST be called from a user gesture (click/keypress). */
  init(): void {
    if (this.ctx) return;
    this.ctx = new AudioContext();
    this.masterGain = this.ctx.createGain();
    this.masterGain.gain.value = this._muted ? 0 : this._volume;
    this.masterGain.connect(this.ctx.destination);

    // Restore persisted prefs
    const stored = localStorage.getItem('hxi_sound_volume');
    if (stored !== null) this._volume = parseFloat(stored);
    this.masterGain.gain.value = this._muted ? 0 : this._volume;
  }

  setVolume(v: number): void {
    this._volume = Math.max(0, Math.min(1, v));
    localStorage.setItem('hxi_sound_volume', String(this._volume));
    if (this.masterGain && !this._muted) {
      this.masterGain.gain.setTargetAtTime(this._volume, this.ctx!.currentTime, 0.05);
    }
  }

  setMuted(m: boolean): void {
    this._muted = m;
    if (!this.ctx) { if (!m) this.init(); return; }
    if (this.masterGain) {
      this.masterGain.gain.setTargetAtTime(
        m ? 0 : this._volume, this.ctx.currentTime, 0.05,
      );
    }
    if (!m) this.startHeartbeat();
    else this.stopHeartbeat();
  }

  /** Sync with WebSocket connection state — silence the mesh on disconnect. */
  setConnected(c: boolean): void {
    this._connected = c;
    if (!c) {
      this.stopHeartbeat();
      this.playDreamExit(); // fade out any ambient drone
    } else if (!this._muted) {
      this.startHeartbeat();
    }
  }

  // ── Heartbeat: low thump at ~1.2s intervals ──

  startHeartbeat(): void {
    if (this.heartbeatInterval) return;
    this.playHeartbeat();
    this.heartbeatInterval = setInterval(() => {
      if (this._connected) this.playHeartbeat();
    }, 1200);
  }

  stopHeartbeat(): void {
    if (this.heartbeatInterval) {
      clearInterval(this.heartbeatInterval);
      this.heartbeatInterval = null;
    }
  }

  playHeartbeat(): void {
    if (!this.ctx || !this.masterGain) return;
    const t = this.ctx.currentTime;
    const osc = this.ctx.createOscillator();
    const gain = this.ctx.createGain();
    osc.type = 'sine';
    osc.frequency.value = 55;
    gain.gain.setValueAtTime(0, t);
    gain.gain.linearRampToValueAtTime(0.4, t + 0.01);  // 10ms attack
    gain.gain.exponentialRampToValueAtTime(0.001, t + 0.35); // 300ms release
    osc.connect(gain).connect(this.masterGain);
    osc.start(t);
    osc.stop(t + 0.4);
  }

  // ── Intent routing: ascending chime ──

  playIntentRouting(): void {
    if (!this.ctx || !this.masterGain || !this._connected) return;
    const t = this.ctx.currentTime;

    [440, 660].forEach((freq, i) => {
      const osc = this.ctx!.createOscillator();
      const gain = this.ctx!.createGain();
      osc.type = 'sine';
      osc.frequency.value = freq;
      const offset = i * 0.06;
      gain.gain.setValueAtTime(0, t + offset);
      gain.gain.linearRampToValueAtTime(0.15, t + offset + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.001, t + offset + 0.25);
      osc.connect(gain).connect(this.masterGain!);
      osc.start(t + offset);
      osc.stop(t + offset + 0.3);
    });
  }

  // ── Consensus: three tones resolving to unison ──

  playConsensus(): void {
    if (!this.ctx || !this.masterGain || !this._connected) return;
    const t = this.ctx.currentTime;
    const target = 440;

    [380, 440, 520].forEach((startFreq) => {
      const osc = this.ctx!.createOscillator();
      const gain = this.ctx!.createGain();
      osc.type = 'sine';
      osc.frequency.setValueAtTime(startFreq, t);
      osc.frequency.linearRampToValueAtTime(target, t + 0.5);
      gain.gain.setValueAtTime(0.1, t);
      gain.gain.exponentialRampToValueAtTime(0.001, t + 0.8);
      osc.connect(gain).connect(this.masterGain!);
      osc.start(t);
      osc.stop(t + 0.85);
    });
  }

  // ── Self-mod spawn: rising shimmer sweep ──

  playSelfModSpawn(): void {
    if (!this.ctx || !this.masterGain || !this._connected) return;
    const t = this.ctx.currentTime;

    // Main sweep
    const osc = this.ctx.createOscillator();
    const gain = this.ctx.createGain();
    osc.type = 'sine';
    osc.frequency.setValueAtTime(200, t);
    osc.frequency.exponentialRampToValueAtTime(800, t + 0.6);
    gain.gain.setValueAtTime(0.12, t);
    gain.gain.exponentialRampToValueAtTime(0.001, t + 0.7);
    osc.connect(gain).connect(this.masterGain);
    osc.start(t);
    osc.stop(t + 0.75);

    // Shimmer overlay
    const shimmer = this.ctx.createOscillator();
    const sGain = this.ctx.createGain();
    shimmer.type = 'triangle';
    shimmer.frequency.setValueAtTime(2000, t);
    shimmer.frequency.exponentialRampToValueAtTime(4000, t + 0.5);
    sGain.gain.setValueAtTime(0.03, t);
    sGain.gain.exponentialRampToValueAtTime(0.001, t + 0.55);
    shimmer.connect(sGain).connect(this.masterGain);
    shimmer.start(t);
    shimmer.stop(t + 0.6);
  }

  // ── Dream mode enter: warm ambient drone ──

  playDreamEnter(): void {
    if (!this.ctx || !this.masterGain || !this._connected) return;
    const t = this.ctx.currentTime;

    // Sine pad
    const osc = this.ctx.createOscillator();
    const gain = this.ctx.createGain();
    const filter = this.ctx.createBiquadFilter();
    osc.type = 'sine';
    osc.frequency.value = 80;
    filter.type = 'lowpass';
    filter.frequency.value = 200;
    gain.gain.setValueAtTime(0, t);
    gain.gain.linearRampToValueAtTime(0.15, t + 3); // 3s fade-in
    osc.connect(filter).connect(gain).connect(this.masterGain);
    osc.start(t);
    this.dreamDrone = osc;

    // Noise layer
    const bufferSize = this.ctx.sampleRate * 5;
    const noiseBuffer = this.ctx.createBuffer(1, bufferSize, this.ctx.sampleRate);
    const output = noiseBuffer.getChannelData(0);
    for (let i = 0; i < bufferSize; i++) output[i] = Math.random() * 2 - 1;
    const noise = this.ctx.createBufferSource();
    noise.buffer = noiseBuffer;
    noise.loop = true;
    const nFilter = this.ctx.createBiquadFilter();
    nFilter.type = 'lowpass';
    nFilter.frequency.value = 150;
    const nGain = this.ctx.createGain();
    nGain.gain.setValueAtTime(0, t);
    nGain.gain.linearRampToValueAtTime(0.04, t + 3);
    noise.connect(nFilter).connect(nGain).connect(this.masterGain);
    noise.start(t);
    this.dreamNoise = noise;
  }

  // ── Dream mode exit: fade out drone ──

  playDreamExit(): void {
    if (!this.ctx) return;
    const t = this.ctx.currentTime;

    if (this.dreamDrone) {
      try {
        this.dreamDrone.stop(t + 2);
      } catch { /* already stopped */ }
      this.dreamDrone = null;
    }
    if (this.dreamNoise) {
      try {
        this.dreamNoise.stop(t + 2);
      } catch { /* already stopped */ }
      this.dreamNoise = null;
    }
  }

  // ── Trust update: quiet ping ──

  playTrustPing(positive: boolean): void {
    if (!this.ctx || !this.masterGain || !this._connected) return;
    const t = this.ctx.currentTime;
    const osc = this.ctx.createOscillator();
    const gain = this.ctx.createGain();
    osc.type = 'sine';
    osc.frequency.value = positive ? 880 : 440;
    gain.gain.setValueAtTime(0.05, t);
    gain.gain.exponentialRampToValueAtTime(0.001, t + 0.05);
    osc.connect(gain).connect(this.masterGain);
    osc.start(t);
    osc.stop(t + 0.08);
  }

  // ── Error: dissonant muted note ──

  playError(): void {
    if (!this.ctx || !this.masterGain || !this._connected) return;
    const t = this.ctx.currentTime;

    [200, 207].forEach((freq) => {
      const osc = this.ctx!.createOscillator();
      const gain = this.ctx!.createGain();
      osc.type = 'sine';
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0.1, t);
      gain.gain.exponentialRampToValueAtTime(0.001, t + 0.3);
      osc.connect(gain).connect(this.masterGain!);
      osc.start(t);
      osc.stop(t + 0.35);
    });
  }

  // ── DAG step completion: ascending chime (AD-391) ──

  playStepComplete(stepIndex: number, totalSteps: number): void {
    if (!this.ctx || !this.masterGain || !this._connected) return;
    const t = this.ctx.currentTime;
    const freq = 523 * Math.pow(2, (stepIndex * 4) / (12 * totalSteps));
    const isFinal = stepIndex === totalSteps - 1;
    const duration = isFinal ? 0.4 : 0.2;

    const osc = this.ctx.createOscillator();
    const gain = this.ctx.createGain();
    osc.type = 'sine';
    osc.frequency.value = freq;
    gain.gain.setValueAtTime(0, t);
    gain.gain.linearRampToValueAtTime(0.08, t + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.001, t + duration);
    osc.connect(gain).connect(this.masterGain);
    osc.start(t);
    osc.stop(t + duration + 0.05);

    // Final step: play completion chord (all accumulated notes)
    if (isFinal && totalSteps > 1) {
      for (let i = 0; i < totalSteps; i++) {
        const chordFreq = 523 * Math.pow(2, (i * 4) / (12 * totalSteps));
        const chordOsc = this.ctx.createOscillator();
        const chordGain = this.ctx.createGain();
        chordOsc.type = 'sine';
        chordOsc.frequency.value = chordFreq;
        chordGain.gain.setValueAtTime(0, t + 0.05);
        chordGain.gain.linearRampToValueAtTime(0.04, t + 0.07);
        chordGain.gain.exponentialRampToValueAtTime(0.001, t + 0.45);
        chordOsc.connect(chordGain).connect(this.masterGain);
        chordOsc.start(t + 0.05);
        chordOsc.stop(t + 0.5);
      }
    }
  }

  // ── Bridge ambient hum (AD-391) ──

  playBridgeHum(state: 'idle' | 'autonomous' | 'attention'): void {
    if (!this.ctx || !this.masterGain) return;
    const t = this.ctx.currentTime;

    // Fade out existing hum
    for (const g of this.bridgeHumGains) {
      g.gain.setTargetAtTime(0, t, 0.5);
    }
    for (const o of this.bridgeHumOscs) {
      try { o.stop(t + 2); } catch { /* already stopped */ }
    }
    this.bridgeHumOscs = [];
    this.bridgeHumGains = [];

    const configs: Record<string, { freqs: number[]; gain: number }> = {
      idle: { freqs: [55], gain: 0.02 },
      autonomous: { freqs: [80, 120], gain: 0.04 },
      attention: { freqs: [65, 98], gain: 0.05 },
    };

    const cfg = configs[state];
    for (const freq of cfg.freqs) {
      const osc = this.ctx.createOscillator();
      const gain = this.ctx.createGain();
      osc.type = 'sine';
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0, t);
      gain.gain.setTargetAtTime(cfg.gain, t, 0.5); // 2s cross-fade
      osc.connect(gain).connect(this.masterGain);
      osc.start(t);
      this.bridgeHumOscs.push(osc);
      this.bridgeHumGains.push(gain);
    }
  }

  // ── Captain return: welcoming two-note chime (AD-391) ──

  playCaptainReturn(): void {
    if (!this.ctx || !this.masterGain || !this._connected) return;
    const t = this.ctx.currentTime;

    [659, 784].forEach((freq, i) => {
      const osc = this.ctx!.createOscillator();
      const gain = this.ctx!.createGain();
      osc.type = 'sine';
      osc.frequency.value = freq;
      const offset = i * 0.21; // 150ms note + 60ms gap
      gain.gain.setValueAtTime(0, t + offset);
      gain.gain.linearRampToValueAtTime(0.1, t + offset + 0.01);
      gain.gain.exponentialRampToValueAtTime(0.001, t + offset + 0.15);
      osc.connect(gain).connect(this.masterGain!);
      osc.start(t + offset);
      osc.stop(t + offset + 0.2);
    });
  }
}

export const soundEngine = new SoundEngine();
