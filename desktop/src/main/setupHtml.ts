/**
 * AD-790: inline first-run setup wizard HTML.
 *
 * Rendered by the Electron main process when ``isFirstRun()`` returns
 * true. Same inline-HTML strategy as ``disconnectedHtml()`` in
 * ``index.ts`` — keeps the wizard < 200 lines, no new build artifact.
 *
 * Four steps:
 *   1. Welcome — short pitch, Continue.
 *   2. Runtime connect — checks ``PROBOS_RUNTIME_URL`` reachability via
 *      a fetch from the renderer; pass/fail messaging.
 *   3. Captain Card — operator's preferred name (saved via IPC; will be
 *      threaded through to the runtime's Captain Card AD-757 once that
 *      REST endpoint exists; for now we just persist locally).
 *   4. Suggested prompts — display 3 starter prompts the operator can
 *      copy/click; "Finish" completes setup and reloads the main window
 *      against the runtime URL.
 *
 * The wizard talks to the main process via ``window.probos.completeSetup({...})``.
 */

export interface SetupHtmlOptions {
  runtimeUrl: string;
  appVersion: string;
}

export function setupHtml({ runtimeUrl, appVersion }: SetupHtmlOptions): string {
  // The wizard is a single-page HTML with vanilla JS step navigation.
  // Escape values that get interpolated to prevent template injection
  // even though they're local-trusted.
  const safeUrl = JSON.stringify(runtimeUrl);
  const safeVersion = JSON.stringify(appVersion);
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Welcome to Yeo</title>
  <style>
    body { background: #0a0a14; color: #e8e8f0; font-family: system-ui, sans-serif;
           margin: 0; padding: 0; height: 100vh; display: flex; flex-direction: column; }
    header { padding: 16px 24px; border-bottom: 1px solid #1a1a2a; font-size: 12px;
             color: #888; letter-spacing: 1px; text-transform: uppercase; }
    main { flex: 1; padding: 32px 48px; overflow-y: auto; }
    h1 { font-size: 22px; margin: 0 0 12px; color: #f0b060; font-weight: 500; }
    p { line-height: 1.55; color: #c0c0c8; }
    .step { display: none; }
    .step.active { display: block; }
    .progress { display: flex; gap: 8px; margin: 16px 0 24px; }
    .dot { width: 28px; height: 4px; border-radius: 2px; background: #2a2a3a; }
    .dot.active { background: #f0b060; }
    .controls { padding: 16px 24px; border-top: 1px solid #1a1a2a;
                display: flex; justify-content: space-between; gap: 12px; }
    button { background: #1f1f2e; color: #e8e8f0; border: 1px solid #3a3a50;
             padding: 8px 18px; border-radius: 6px; cursor: pointer; font-size: 13px; }
    button:hover { background: #2a2a3e; }
    button.primary { border-color: #f0b060; color: #f0b060; }
    button:disabled { opacity: 0.4; cursor: not-allowed; }
    input[type="text"] { background: #14141e; color: #e8e8f0; border: 1px solid #3a3a50;
                         padding: 8px 12px; border-radius: 6px; font-size: 13px; width: 100%;
                         box-sizing: border-box; margin-top: 8px; }
    .runtime-status { margin-top: 16px; padding: 12px; background: #14141e; border-radius: 6px;
                      font-size: 12px; color: #888; }
    .runtime-status.ok { color: #80c080; }
    .runtime-status.fail { color: #d08080; }
    code { background: #14141e; padding: 2px 6px; border-radius: 4px; font-size: 12px; }
    .prompts li { margin: 8px 0; padding: 10px 14px; background: #14141e;
                  border-radius: 6px; cursor: pointer; list-style: none; font-size: 13px; }
    .prompts li:hover { background: #1a1a28; }
    ul { padding-left: 0; }
  </style>
</head>
<body>
  <header>Yeo • Setup • v${appVersion}</header>
  <main>
    <div class="progress" id="progress">
      <div class="dot active"></div>
      <div class="dot"></div>
      <div class="dot"></div>
      <div class="dot"></div>
    </div>

    <section class="step active" data-step="0">
      <h1>Welcome to Yeo</h1>
      <p>Yeo is your personal AI assistant — a chat-first surface backed by
         the ProbOS cognitive mesh running on your machine. This setup wizard
         takes about 30 seconds.</p>
      <p style="color:#888;font-size:12px;margin-top:24px;">You can re-run this
         later from the tray menu (Reset Setup…).</p>
    </section>

    <section class="step" data-step="1">
      <h1>Runtime connection</h1>
      <p>Yeo connects to the ProbOS runtime at <code>${runtimeUrl}</code>.
         Click below to verify it's reachable.</p>
      <button id="probe-btn" type="button">Check runtime</button>
      <div class="runtime-status" id="probe-result">Not checked yet.</div>
    </section>

    <section class="step" data-step="2">
      <h1>What should Yeo call you?</h1>
      <p>This will appear in greetings and is shared with the agent crew as
         your operator profile. You can change it later from Settings.</p>
      <input id="captain-name" type="text" placeholder="Captain" maxlength="64" />
    </section>

    <section class="step" data-step="3">
      <h1>Try one of these to get started</h1>
      <p>Click a prompt to launch Yeo with it pre-loaded, or click Finish to
         start with an empty chat.</p>
      <ul class="prompts">
        <li data-prompt="Brief me on the day - what should I focus on right now?">Brief me on the day</li>
        <li data-prompt="What can you do? Show me your skills.">What can you do?</li>
        <li data-prompt="Help me draft a quick note about ">Help me draft a note</li>
      </ul>
    </section>
  </main>
  <div class="controls">
    <button id="back-btn" type="button" disabled>Back</button>
    <button id="next-btn" class="primary" type="button">Continue</button>
  </div>

  <script>
    const RUNTIME_URL = ${safeUrl};
    const APP_VERSION = ${safeVersion};
    let step = 0;
    const total = 4;
    const stepNodes = Array.from(document.querySelectorAll('.step'));
    const dotNodes = Array.from(document.querySelectorAll('#progress .dot'));
    const backBtn = document.getElementById('back-btn');
    const nextBtn = document.getElementById('next-btn');
    const probeBtn = document.getElementById('probe-btn');
    const probeResult = document.getElementById('probe-result');
    const nameInput = document.getElementById('captain-name');
    const promptList = document.querySelector('.prompts');
    let selectedPrompt = null;

    function renderStep() {
      stepNodes.forEach((n, i) => n.classList.toggle('active', i === step));
      dotNodes.forEach((n, i) => n.classList.toggle('active', i <= step));
      backBtn.disabled = step === 0;
      nextBtn.textContent = step === total - 1 ? 'Finish' : 'Continue';
    }

    backBtn.addEventListener('click', () => { if (step > 0) { step--; renderStep(); } });
    nextBtn.addEventListener('click', async () => {
      if (step < total - 1) { step++; renderStep(); return; }
      const captainName = (nameInput.value || '').trim() || 'Captain';
      const result = await window.probos?.completeSetup({
        captainName,
        suggestedPrompt: selectedPrompt,
        setupVersion: 1,
      });
      // The main process reloads the window onto the runtime URL on success.
    });

    probeBtn.addEventListener('click', async () => {
      probeResult.textContent = 'Checking...';
      probeResult.className = 'runtime-status';
      try {
        // BF (2026-05-22): use main-process IPC instead of renderer
        // fetch. The wizard is loaded from a data: URL which has a null
        // origin; cross-origin fetch to 127.0.0.1 fails CORS preflight.
        const probos = window.probos;
        const r = probos && typeof probos.checkRuntime === 'function'
          ? await probos.checkRuntime()
          : { ok: false, error: 'IPC bridge missing (preload not loaded?)' };
        if (r.ok) {
          probeResult.textContent = 'OK - ProbOS runtime is responding.';
          probeResult.className = 'runtime-status ok';
        } else if (r.status) {
          probeResult.textContent = 'Runtime returned status ' + r.status + '.';
          probeResult.className = 'runtime-status fail';
        } else {
          // Show the underlying error to aid diagnosis.
          probeResult.textContent = 'Could not reach the runtime: ' +
            (r.error || 'unknown error') +
            '. Make sure probos serve is running at ' + RUNTIME_URL + '.';
          probeResult.className = 'runtime-status fail';
        }
      } catch (err) {
        probeResult.textContent = 'Probe threw: ' + String(err);
        probeResult.className = 'runtime-status fail';
      }
    });

    promptList?.addEventListener('click', (e) => {
      const t = e.target;
      if (t && t.dataset && t.dataset.prompt) {
        selectedPrompt = t.dataset.prompt;
        Array.from(promptList.children).forEach((c) => {
          c.style.borderLeft = c === t ? '3px solid #f0b060' : '';
          c.style.paddingLeft = c === t ? '11px' : '14px';
        });
      }
    });

    renderStep();
  </script>
</body>
</html>`;
}
