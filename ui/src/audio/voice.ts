/* Voice output — browser SpeechSynthesis (zero dependencies) */

let voicesLoaded = false;
let cachedVoice: SpeechSynthesisVoice | null = null;

function findPreferredVoice(): SpeechSynthesisVoice | null {
  if (cachedVoice) return cachedVoice;
  if (!('speechSynthesis' in window)) return null;
  const voices = speechSynthesis.getVoices();
  if (voices.length === 0) return null;
  voicesLoaded = true;

  // Prefer natural-sounding English voices
  const preferred = voices.find(v =>
    v.lang.startsWith('en') && (
      v.name.includes('Google') ||
      v.name.includes('Natural') ||
      v.name.includes('Samantha') ||
      v.name.includes('Microsoft Zira') ||
      v.name.includes('Microsoft David')
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
