/* Voice output — browser SpeechSynthesis (zero dependencies) */

let voicesLoaded = false;
let cachedVoice: SpeechSynthesisVoice | null = null;

function findPreferredVoice(): SpeechSynthesisVoice | null {
  if (cachedVoice) return cachedVoice;
  if (!('speechSynthesis' in window)) return null;
  const voices = speechSynthesis.getVoices();
  if (voices.length === 0) return null;
  voicesLoaded = true;

  // Check user preference first
  const savedName = localStorage.getItem('hxi_voice_name');
  if (savedName) {
    const saved = voices.find(v => v.name === savedName);
    if (saved) {
      cachedVoice = saved;
      return saved;
    }
  }

  // Auto-detect best available (Edge neural first)
  const preferred = voices.find(v =>
    v.lang.startsWith('en') && v.name.includes('Online (Natural)')
  ) || voices.find(v =>
    v.lang.startsWith('en') && v.name.includes('Online')
  ) || voices.find(v =>
    v.lang.startsWith('en') && (
      v.name.includes('Google US English') ||
      v.name.includes('Google UK English') ||
      v.name.includes('Natural') ||
      v.name.includes('Samantha')
    )
  ) || voices.find(v => v.lang.startsWith('en')) || null;

  cachedVoice = preferred;
  return preferred;
}

// Preload voices (some browsers load them async)
if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
  speechSynthesis.addEventListener('voiceschanged', () => {
    cachedVoice = null;
    findPreferredVoice();
  });
}

export function speakResponse(text: string): void {
  if (!('speechSynthesis' in window)) return;

  // Cancel any ongoing speech
  speechSynthesis.cancel();

  const utterance = new SpeechSynthesisUtterance(text);
  utterance.rate = 0.95;
  utterance.pitch = 0.9;
  utterance.volume = 0.8;

  const voice = findPreferredVoice();
  if (voice) utterance.voice = voice;

  speechSynthesis.speak(utterance);
}

export function stopSpeaking(): void {
  if ('speechSynthesis' in window) {
    speechSynthesis.cancel();
  }
}

export function getAvailableVoices(): SpeechSynthesisVoice[] {
  if (!('speechSynthesis' in window)) return [];
  return speechSynthesis.getVoices().filter(v => v.lang.startsWith('en'));
}

export function setPreferredVoiceName(name: string | null): void {
  cachedVoice = null;
  if (name) {
    localStorage.setItem('hxi_voice_name', name);
  } else {
    localStorage.removeItem('hxi_voice_name');
  }
}

export function getCurrentVoiceName(): string {
  const voice = findPreferredVoice();
  return voice?.name || 'Default';
}
