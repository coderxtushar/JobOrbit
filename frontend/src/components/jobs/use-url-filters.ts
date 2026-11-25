"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";

import { readFilters, writeFilters, type JobFilters, type JobStatus } from "./job-utils";

/** Job filters held in the URL, so a filtered view can be bookmarked, shared and reloaded. */
export function useUrlFilters(fixedStatus?: JobStatus) {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const query = searchParams.toString();

  const filters = useMemo(() => readFilters(new URLSearchParams(query), fixedStatus), [query, fixedStatus]);

  const replace = useCallback(
    (params: URLSearchParams) => {
      const text = params.toString();
      router.replace(text ? `${pathname}?${text}` : pathname, { scroll: false });
    },
    [pathname, router],
  );

  /** Merge a change into the filters. Any change other than paging returns to page one. */
  const update = useCallback(
    (patch: Partial<JobFilters>) => {
      const next = { ...readFilters(new URLSearchParams(query), fixedStatus), ...patch };
      if (!("offset" in patch)) next.offset = 0;
      replace(writeFilters(new URLSearchParams(query), next, fixedStatus));
    },
    [fixedStatus, query, replace],
  );

  const reset = useCallback(() => {
    const params = new URLSearchParams(query);
    for (const key of ["status", "source", "company", "min_score", "max_age_days", "include_duplicates", "offset"]) {
      params.delete(key);
    }
    replace(params);
  }, [query, replace]);

  const rawSelected = Number(searchParams.get("job"));
  const selectedId = Number.isInteger(rawSelected) && rawSelected > 0 ? rawSelected : null;

  const setSelectedId = useCallback(
    (id: number | null) => {
      const params = new URLSearchParams(query);
      if (id === null) params.delete("job");
      else params.set("job", String(id));
      replace(params);
    },
    [query, replace],
  );

  const setParam = useCallback(
    (key: string, value: string | null) => {
      const params = new URLSearchParams(query);
      if (value === null) params.delete(key);
      else params.set(key, value);
      replace(params);
    },
    [query, replace],
  );

  return { filters, update, reset, selectedId, setSelectedId, searchParams, setParam };
}

/**
 * A text input bound to a URL value with a debounce. Typing updates locally at once and
 * commits after `delay`; a URL change from elsewhere (the top bar's search) replaces the text
 * unless it is just our own commit coming back.
 */
export function useDebouncedText(urlValue: string, commit: (value: string) => void, delay = 300) {
  const [text, setText] = useState(urlValue);
  const [synced, setSynced] = useState(urlValue);
  const [pushed, setPushed] = useState<string | null>(null);

  if (urlValue !== synced) {
    setSynced(urlValue);
    if (urlValue !== pushed) setText(urlValue);
  }

  useEffect(() => {
    const trimmed = text.trim();
    if (trimmed === urlValue.trim()) return;
    const timer = window.setTimeout(() => {
      setPushed(trimmed);
      commit(trimmed);
    }, delay);
    return () => window.clearTimeout(timer);
  }, [commit, delay, text, urlValue]);

  return [text, setText] as const;
}

function subscribeMedia(query: string) {
  return (callback: () => void) => {
    const list = window.matchMedia(query);
    list.addEventListener("change", callback);
    return () => list.removeEventListener("change", callback);
  };
}

/** True when the media query matches. Server render assumes false. */
export function useMediaQuery(query: string): boolean {
  const subscribe = useMemo(() => subscribeMedia(query), [query]);
  return useSyncExternalStore(
    subscribe,
    () => window.matchMedia(query).matches,
    () => false,
  );
}
