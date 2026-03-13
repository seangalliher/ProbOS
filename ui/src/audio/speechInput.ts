/* Voice input — browser SpeechRecognition API (zero dependencies) */

// Extend Window for vendor-prefixed API
declare global {
  interface Window {
    SpeechRecognition?: new () => SpeechRecognitionInstance;
    webkitSpeechRecognition?: new () => SpeechRecognitionInstance;
  }
}

interface SpeechRecognitionInstance {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: { results: { [index: number]: { [index: number]: { transcript: string } } } }) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start(): void;
  abort(): void;
  stop(): void;
}

export function isSpeechRecognitionSupported(): boolean {
  return typeof window !== 'undefined' &&
    ('SpeechRecognition' in window || 'webkitSpeechRecognition' in window);
}

let activeRecognition: SpeechRecognitionInstance | null = null;

export function startListening(
  onResult: (text: string) => void,
  onEnd?: () => void,
  onError?: (error: string) => void,
): void {
  if (!isSpeechRecognitionSupported()) {
    onError?.('Speech recognition not supported in this browser');
    return;
  }

  // Stop any active session
  stopListening();

  const Ctor = window.SpeechRecognition || window.webkitSpeechRecognition!;
  const recognition = new Ctor();
  recognition.continuous = false;
  recognition.interimResults = false;
  recognition.lang = 'en-US';

  recognition.onresult = (event) => {
    const text = event.results[0][0].transcript;
    onResult(text);
  };

  recognition.onerror = (event) => {
    if (event.error !== 'aborted') {
      onError?.(event.error);
    }
  };

  recognition.onend = () => {
    activeRecognition = null;
    onEnd?.();
  };

  activeRecognition = recognition;
  recognition.start();
}

export function stopListening(): void {
  if (activeRecognition) {
    try { activeRecognition.abort(); } catch { /* already stopped */ }
    activeRecognition = null;
  }
}

export function isListening(): boolean {
  return activeRecognition !== null;
}
