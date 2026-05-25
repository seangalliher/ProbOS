/**
 * BF-308: PCM capture AudioWorklet — the "follow-up shim" promised by
 * AD-733c-7-5-1 that was never actually built. Without this, the mic
 * stream opens (address-bar icon lights up) but no PCM frames ever reach
 * ``_processFrame`` in voiceActivity.ts, so Silero never scores, no
 * speech_start fires, and downstream consumers (transformersStt,
 * conversationController) sit forever waiting for events that never come.
 *
 * Runs in the AudioWorkletGlobalScope. The AudioContext is created at
 * 16 kHz so the browser-side resampler hands us mono PCM at the rate
 * Silero wants. We batch the worklet's native 128-sample blocks into
 * 480-sample frames (matching ``FRAME_SAMPLES`` in voiceActivity.ts —
 * 30 ms @ 16 kHz) and post each frame to the main thread.
 *
 * Privacy invariant (AD-733c-7): no audio bytes leave the browser. This
 * worklet only forwards PCM frames to the same-origin main thread; the
 * VAD scoring + endpoint POST happen there.
 */
const FRAME_SAMPLES = 480;

class PcmCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._buffer = new Float32Array(FRAME_SAMPLES);
    this._offset = 0;
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0) return true;
    const channel = input[0];
    if (!channel || channel.length === 0) return true;
    let read = 0;
    while (read < channel.length) {
      const room = FRAME_SAMPLES - this._offset;
      const take = Math.min(room, channel.length - read);
      this._buffer.set(channel.subarray(read, read + take), this._offset);
      this._offset += take;
      read += take;
      if (this._offset >= FRAME_SAMPLES) {
        // Ship a defensive copy — the worklet reuses its scratch buffer.
        const out = new Float32Array(this._buffer);
        this.port.postMessage(out, [out.buffer]);
        this._offset = 0;
      }
    }
    return true;
  }
}

registerProcessor('pcm-capture', PcmCaptureProcessor);
