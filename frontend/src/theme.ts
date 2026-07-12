/**
 * Theme generation utilities.
 * Derives CSS variables from a hex theme color and applies them to the document.
 */

import type { AppearanceConfig } from './types';

/** Convert hex color to HSL components. */
function hexToHSL(hex: string): { h: number; s: number; l: number } {
  // Strip # and parse
  const clean = hex.replace('#', '');
  const r = parseInt(clean.substring(0, 2), 16) / 255;
  const g = parseInt(clean.substring(2, 4), 16) / 255;
  const b = parseInt(clean.substring(4, 6), 16) / 255;

  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const delta = max - min;

  let h = 0;
  let s = 0;
  const l = (max + min) / 2;

  if (delta !== 0) {
    s = l > 0.5 ? delta / (2 - max - min) : delta / (max + min);

    if (max === r) {
      h = ((g - b) / delta + (g < b ? 6 : 0)) / 6;
    } else if (max === g) {
      h = ((b - r) / delta + 2) / 6;
    } else {
      h = ((r - g) / delta + 4) / 6;
    }
  }

  return {
    h: Math.round(h * 360),
    s: Math.round(s * 100),
    l: Math.round(l * 100),
  };
}

/** Format HSL values as CSS hsl() string. */
function hslStr(h: number, s: number, l: number): string {
  return `hsl(${h}, ${s}%, ${l}%)`;
}

/** Derive accent color CSS variables from a hex theme color. */
function deriveAccentVars(hex: string): Record<string, string> {
  const { h, s, l } = hexToHSL(hex);

  return {
    '--accent': hslStr(h, s, l),
    '--accent-dim': hslStr(h, Math.min(s, 32), Math.max(l - 24, 18)),
    '--accent-hover': hslStr(h, Math.min(s, 92), Math.min(l + 4, 68)),
  };
}

/** Dark mode base variables. */
const DARK_VARS: Record<string, string> = {
  '--bg-primary': '#121212',
  '--bg-secondary': '#191919',
  '--bg-tertiary': '#222222',
  '--bg-hover': '#272727',
  '--text-primary': '#f2f2f2',
  '--text-secondary': '#bdbdbd',
  '--text-muted': '#8a8a8a',
  '--border': '#2b2b2b',
  '--border-light': '#232323',
};

/** Light mode base variables. */
const LIGHT_VARS: Record<string, string> = {
  '--bg-primary': '#f8fafc',
  '--bg-secondary': '#ffffff',
  '--bg-tertiary': '#eef2f7',
  '--bg-hover': '#e7ebf1',
  '--text-primary': '#1c1d1f',
  '--text-secondary': '#4b5563',
  '--text-muted': '#6b7280',
  '--border': '#d7dce5',
  '--border-light': '#e7ecf3',
};

/** Determine effective mode: auto resolves via system preference. */
function resolveMode(mode: string): 'dark' | 'light' {
  if (mode === 'auto') {
    return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  }
  return mode === 'light' ? 'light' : 'dark';
}

/** Apply the full theme to the document root. */
export function applyTheme(config: AppearanceConfig): void {
  const root = document.documentElement;
  const effective = resolveMode(config.mode);

  // Set data-theme attribute for CSS selectors
  root.setAttribute('data-theme', config.mode);

  // Apply base color vars for the effective mode
  const baseVars = effective === 'light' ? LIGHT_VARS : DARK_VARS;
  for (const [key, value] of Object.entries(baseVars)) {
    root.style.setProperty(key, value);
  }

  // Apply accent color vars derived from theme_color
  const accentVars = deriveAccentVars(config.theme_color);
  for (const [key, value] of Object.entries(accentVars)) {
    root.style.setProperty(key, value);
  }

  // Apply wallpaper CSS variables
  root.style.setProperty('--wallpaper-blur', `${config.wallpaper_blur}px`);
  root.style.setProperty('--wallpaper-opacity', `${config.wallpaper_opacity}`);

  // Apply font size
  root.style.setProperty('--base-font-size', `${config.font_size}px`);
  document.body.style.fontSize = `${config.font_size}px`;
}

/** Remove all inline theme overrides (reset to CSS defaults). */
export function removeTheme(): void {
  const root = document.documentElement;
  root.removeAttribute('data-theme');

  const allVars = [
    ...Object.keys(DARK_VARS),
    '--accent', '--accent-dim', '--accent-hover',
    '--wallpaper-blur', '--wallpaper-opacity', '--base-font-size',
  ];
  for (const key of allVars) {
    root.style.removeProperty(key);
  }
  document.body.style.removeProperty('font-size');
}

/** Set up auto-mode listener to re-apply theme when system preference changes. */
export function setupAutoModeListener(config: AppearanceConfig, onApply: () => void): (() => void) | null {
  if (config.mode !== 'auto') return null;

  const mq = window.matchMedia('(prefers-color-scheme: light)');
  const handler = () => onApply();
  mq.addEventListener('change', handler);
  return () => mq.removeEventListener('change', handler);
}
