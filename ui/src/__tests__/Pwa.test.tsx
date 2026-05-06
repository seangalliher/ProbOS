/**
 * AD-473 v1 — Mobile PWA test coverage.
 *
 * Coverage:
 *   - Manifest JSON shape (4 tests)
 *   - registerServiceWorker helper (4 tests)
 *   - InstallPrompt component (5 tests)
 *   - Viewport meta verification (1 test) — verifies index.html line 5 unchanged
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react';
import { readFileSync } from 'fs';
import { resolve } from 'path';

import { InstallPrompt } from '../components/InstallPrompt';
import { registerServiceWorker } from '../pwa/register';

// ---------- Manifest ----------

describe('manifest.webmanifest', () => {
  const manifestPath = resolve(__dirname, '../../public/manifest.webmanifest');
  const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));

  it('declares all 7 required PWA fields', () => {
    expect(manifest.name).toBe('ProbOS HXI');
    expect(manifest.short_name).toBe('ProbOS');
    expect(manifest.start_url).toBe('/');
    expect(manifest.display).toBe('standalone');
    expect(manifest.theme_color).toBe('#0a0a12');
    expect(manifest.background_color).toBe('#0a0a12');
    expect(Array.isArray(manifest.icons)).toBe(true);
  });

  it('declares at least one 192x192 icon', () => {
    const icon192 = manifest.icons.find((i: any) => i.sizes === '192x192');
    expect(icon192).toBeDefined();
    expect(icon192.src).toMatch(/icon-192\.svg$/);
  });

  it('declares at least one 512x512 icon', () => {
    const icon512 = manifest.icons.find((i: any) => i.sizes === '512x512');
    expect(icon512).toBeDefined();
    expect(icon512.src).toMatch(/icon-512\.svg$/);
  });

  it('declares a maskable icon for Android adaptive icons', () => {
    const maskable = manifest.icons.find((i: any) => i.purpose === 'maskable');
    expect(maskable).toBeDefined();
  });
});

// ---------- registerServiceWorker ----------

describe('registerServiceWorker', () => {
  let originalSW: any;

  beforeEach(() => {
    originalSW = (navigator as any).serviceWorker;
  });

  afterEach(() => {
    if (originalSW === undefined) {
      delete (navigator as any).serviceWorker;
    } else {
      Object.defineProperty(navigator, 'serviceWorker', {
        value: originalSW,
        configurable: true,
      });
    }
  });

  it('returns null when serviceWorker API is unavailable', async () => {
    delete (navigator as any).serviceWorker;
    const result = await registerServiceWorker();
    expect(result).toBeNull();
  });

  it('returns the registration when API is available', async () => {
    const fakeRegistration = { scope: '/' };
    Object.defineProperty(navigator, 'serviceWorker', {
      value: { register: vi.fn().mockResolvedValue(fakeRegistration) },
      configurable: true,
    });
    const result = await registerServiceWorker();
    expect(result).toBe(fakeRegistration);
  });

  it('calls register with /sw.js path', async () => {
    const register = vi.fn().mockResolvedValue({ scope: '/' });
    Object.defineProperty(navigator, 'serviceWorker', {
      value: { register },
      configurable: true,
    });
    await registerServiceWorker();
    expect(register).toHaveBeenCalledWith('/sw.js');
  });

  it('returns null and logs on registration failure (tier-2 log-and-degrade)', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    Object.defineProperty(navigator, 'serviceWorker', {
      value: { register: vi.fn().mockRejectedValue(new Error('boom')) },
      configurable: true,
    });
    const result = await registerServiceWorker();
    expect(result).toBeNull();
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });
});

// ---------- InstallPrompt ----------

describe('InstallPrompt', () => {
  it('renders nothing before beforeinstallprompt fires', () => {
    const { container } = render(<InstallPrompt />);
    expect(container.firstChild).toBeNull();
  });

  it('renders install button after beforeinstallprompt fires', () => {
    render(<InstallPrompt />);
    const event: any = new Event('beforeinstallprompt');
    event.prompt = vi.fn().mockResolvedValue(undefined);
    event.userChoice = Promise.resolve({ outcome: 'accepted', platform: 'web' });
    act(() => {
      window.dispatchEvent(event);
    });
    expect(screen.getByTestId('install-prompt')).toBeInTheDocument();
    expect(screen.getByTestId('install-prompt-install')).toBeInTheDocument();
  });

  it('calls prompt() when install button clicked', async () => {
    render(<InstallPrompt />);
    const promptFn = vi.fn().mockResolvedValue(undefined);
    const event: any = new Event('beforeinstallprompt');
    event.prompt = promptFn;
    event.userChoice = Promise.resolve({ outcome: 'accepted', platform: 'web' });
    act(() => {
      window.dispatchEvent(event);
    });
    fireEvent.click(screen.getByTestId('install-prompt-install'));
    await waitFor(() => expect(promptFn).toHaveBeenCalled());
  });

  it('dismisses when user clicks dismiss button', () => {
    render(<InstallPrompt />);
    const event: any = new Event('beforeinstallprompt');
    event.prompt = vi.fn().mockResolvedValue(undefined);
    event.userChoice = Promise.resolve({ outcome: 'dismissed', platform: 'web' });
    act(() => {
      window.dispatchEvent(event);
    });
    fireEvent.click(screen.getByTestId('install-prompt-dismiss'));
    expect(screen.queryByTestId('install-prompt')).not.toBeInTheDocument();
  });

  it('dismisses on appinstalled event', () => {
    render(<InstallPrompt />);
    const event: any = new Event('beforeinstallprompt');
    event.prompt = vi.fn().mockResolvedValue(undefined);
    event.userChoice = Promise.resolve({ outcome: 'accepted', platform: 'web' });
    act(() => {
      window.dispatchEvent(event);
    });
    expect(screen.getByTestId('install-prompt')).toBeInTheDocument();
    act(() => {
      window.dispatchEvent(new Event('appinstalled'));
    });
    expect(screen.queryByTestId('install-prompt')).not.toBeInTheDocument();
  });
});

// ---------- Viewport meta (regression guard) ----------

describe('index.html viewport meta', () => {
  it('declares mobile-friendly viewport (responsive viewport already shipped per roadmap line 1544)', () => {
    const indexHtml = readFileSync(resolve(__dirname, '../../index.html'), 'utf8');
    expect(indexHtml).toMatch(/<meta\s+name="viewport"\s+content="width=device-width,\s*initial-scale=1\.0"\s*\/?>/);
  });
});
