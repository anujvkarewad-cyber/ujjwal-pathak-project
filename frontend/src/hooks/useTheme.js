import { useSyncExternalStore } from 'react';

const STORAGE_KEY = 'up-mentor-theme';
const listeners = new Set();

const getInitial = () => {
  if (typeof window === 'undefined') return 'light';
  return localStorage.getItem(STORAGE_KEY) || 'light';
};

let currentTheme = getInitial();

// Apply on module load so <html> is correct before any component mounts
if (typeof document !== 'undefined') {
  if (currentTheme === 'dark') document.documentElement.classList.add('dark');
  else document.documentElement.classList.remove('dark');
}

const setThemeGlobal = (next) => {
  currentTheme = next;
  if (typeof document !== 'undefined') {
    if (next === 'dark') document.documentElement.classList.add('dark');
    else document.documentElement.classList.remove('dark');
    localStorage.setItem(STORAGE_KEY, next);
  }
  listeners.forEach((l) => l());
};

const subscribe = (cb) => {
  listeners.add(cb);
  return () => listeners.delete(cb);
};

const getSnapshot = () => currentTheme;

export function useTheme() {
  const theme = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
  return {
    theme,
    setTheme: setThemeGlobal,
    toggle: () => setThemeGlobal(currentTheme === 'dark' ? 'light' : 'dark'),
  };
}
