/**
 * ProbOS HXI — Install Prompt (AD-473c).
 *
 * Listens for `beforeinstallprompt`, surfaces a stroke-based SVG install
 * button matching HXI principle #3 (no emoji), and dismisses on
 * `appinstalled` or user dismissal. Does NOT auto-render — appears only
 * after `beforeinstallprompt` fires (HXI principle #5: progressive
 * disclosure driven by engagement).
 */
import { useEffect, useState } from 'react';

interface BeforeInstallPromptEvent extends Event {
  prompt(): Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed'; platform: string }>;
}

export function InstallPrompt() {
  const [deferred, setDeferred] = useState<BeforeInstallPromptEvent | null>(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    const onBeforeInstall = (e: Event) => {
      e.preventDefault();
      setDeferred(e as BeforeInstallPromptEvent);
    };
    const onInstalled = () => {
      setDeferred(null);
      setDismissed(true);
    };
    window.addEventListener('beforeinstallprompt', onBeforeInstall);
    window.addEventListener('appinstalled', onInstalled);
    return () => {
      window.removeEventListener('beforeinstallprompt', onBeforeInstall);
      window.removeEventListener('appinstalled', onInstalled);
    };
  }, []);

  if (dismissed || deferred === null) return null;

  const handleInstall = async () => {
    await deferred.prompt();
    const choice = await deferred.userChoice;
    if (choice.outcome !== 'accepted') {
      setDismissed(true);
    }
    setDeferred(null);
  };

  const handleDismiss = () => {
    setDismissed(true);
    setDeferred(null);
  };

  return (
    <div
      data-testid="install-prompt"
      style={{
        position: 'fixed',
        bottom: 16,
        right: 16,
        zIndex: 30,
        display: 'flex',
        gap: 8,
        padding: '8px 12px',
        background: 'rgba(10, 10, 18, 0.85)',
        backdropFilter: 'blur(8px)',
        WebkitBackdropFilter: 'blur(8px)',
        border: '1px solid #f0b060',
        borderRadius: 4,
        color: '#e0dcd4',
        fontFamily: 'Inter, sans-serif',
        fontSize: 12,
      }}
    >
      <button
        data-testid="install-prompt-install"
        onClick={handleInstall}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 6,
          padding: '4px 10px',
          background: 'transparent',
          border: '1px solid #f0b060',
          borderRadius: 2,
          color: '#f0b060',
          cursor: 'pointer',
          font: 'inherit',
        }}
      >
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
          <path d="M6 1 V8 M3 5 L6 8 L9 5 M2 10 H10" stroke="#f0b060" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
        Install ProbOS
      </button>
      <button
        data-testid="install-prompt-dismiss"
        onClick={handleDismiss}
        aria-label="Dismiss"
        style={{
          padding: '4px 8px',
          background: 'transparent',
          border: '1px solid #666680',
          borderRadius: 2,
          color: '#666680',
          cursor: 'pointer',
          font: 'inherit',
        }}
      >
        <svg width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden="true">
          <path d="M2 2 L8 8 M8 2 L2 8" stroke="#666680" strokeWidth="1.5" strokeLinecap="round"/>
        </svg>
      </button>
    </div>
  );
}
