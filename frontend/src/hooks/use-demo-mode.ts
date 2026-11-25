"use client";

import { useHealth } from "./use-health";

/**
 * Whether the API runs the public demo: `true`, `false`, or `undefined` while unknown.
 * Queries for features the demo refuses (Gmail tracking) wait for an explicit `false`, so
 * a demo visitor never triggers a refused request.
 */
export function useDemoMode(): boolean | undefined {
  return useHealth().data?.demo_mode;
}
