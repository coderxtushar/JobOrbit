"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/endpoints";
import type { NavCountKey } from "@/lib/constants/navigation";

/**
 * Sidebar badges, each read from a real endpoint. A count that fails to load is simply not
 * shown: a badge is never a guess.
 */
export function useNavCounts(): Partial<Record<NavCountKey, number>> {
  const inbox = useQuery({
    queryKey: ["nav", "inbox"],
    queryFn: () => api.inbox(500),
    refetchInterval: 60_000,
  });
  const review = useQuery({
    queryKey: ["nav", "review"],
    queryFn: () => api.applications({ status: "READY_FOR_REVIEW", limit: 1 }),
    refetchInterval: 60_000,
  });
  const unknown = useQuery({
    queryKey: ["nav", "unknown"],
    queryFn: () => api.applications({ status: "SUBMISSION_UNKNOWN", limit: 1 }),
    refetchInterval: 60_000,
  });
  return {
    inbox: inbox.data?.length,
    review: review.data?.total,
    unknown: unknown.data?.total,
  };
}
