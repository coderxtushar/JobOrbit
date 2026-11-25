"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/endpoints";

/** The API's health payload; also tells the shell whether the backend is reachable. */
export function useHealth() {
  return useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 30_000 });
}
