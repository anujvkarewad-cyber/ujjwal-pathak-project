import { useSyncExternalStore } from 'react';

const STORAGE_KEY = 'up-mentor-theme';
const listeners = new Set();

// Safe storage wrapper: some embedded/preview contexts (sandboxed iframes)
// throw on ANY access to window.localStorage. Falling back to in-memory keeps
// the app booting and the theme toggle working; persistence stays wherever
// storage is available. Behavior is otherwise unchanged.
const memoryStore = {};
const storage = (() => {
  try {
    const t = typeof window !== 'undefined' ? window.localStorage : null;
    if (t) {
      t.getItem(STORAGE_KEY); // probe — throws when blocked
      return t;
    }
    return null;
  } catch {
    return null;
  }
})();

const getStored = () => {
  try {
    return storage ? storage.getItem(STORAGE_KEY) : memoryStore[STORAGE_KEY];
  } catch {
    return memoryStore[STORAGE_KEY];
  }
};

const setStored = (value) => {
  memoryStore[STORAGE_KEY] = value;
  try {
    if (storage) storage.setItem(STORAGE_KEY, value);
  } catch {
    /* storage blocked — in-memory fallback is already set */
  }
};

const getInitial = () => {
  if (typeof window === 'undefined') return 'light';
  return getStored() || 'light';
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
    setStored(next);
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
