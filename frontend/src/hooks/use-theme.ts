"use client";

import { useCallback, useSyncExternalStore } from "react";

import { THEME_STORAGE_KEY } from "@/lib/constants/theme";

/**
 * Theme state without a provider. The class on <html> is the source of truth: the inline
 * script in app/layout.tsx sets it from localStorage before the first paint, and setTheme
 * changes it and remembers the choice. Dark is the default.
 */
export type Theme = "dark" | "light";

const listeners = new Set<() => void>();

function current(): Theme {
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

export function useTheme(): { theme: Theme; resolvedTheme: Theme; setTheme: (theme: Theme) => void } {
  const theme = useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    current,
    () => "dark" as Theme,
  );
  const setTheme = useCallback((next: Theme) => {
    const root = document.documentElement;
    root.classList.toggle("dark", next === "dark");
    root.style.colorScheme = next;
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      /* the choice still applies for this visit */
    }
    listeners.forEach((listener) => listener());
  }, []);
  return { theme, resolvedTheme: theme, setTheme };
}
