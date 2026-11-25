"use client";

import { useCallback, useSyncExternalStore } from "react";

/**
 * Whether the desktop sidebar is collapsed, remembered per browser. Storage can be absent
 * (private mode) or throw; the sidebar then simply starts expanded.
 */
const KEY = "joborbit.sidebar.collapsed";
const listeners = new Set<() => void>();

function read(): boolean {
  try {
    return window.localStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}

export function useSidebarCollapsed(): [boolean, (value: boolean) => void] {
  const collapsed = useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    read,
    () => false,
  );
  const set = useCallback((value: boolean) => {
    try {
      window.localStorage.setItem(KEY, value ? "1" : "0");
    } catch {
      /* not persisted; still applied for this session below */
    }
    listeners.forEach((listener) => listener());
  }, []);
  return [collapsed, set];
}
