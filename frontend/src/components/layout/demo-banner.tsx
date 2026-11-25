"use client";

import { FlaskConical } from "lucide-react";

import { useHealth } from "@/hooks/use-health";

const REPO_URL = "https://github.com/coderxtushar/JobOrbit";

/** Shown only when the API runs in demo mode: says plainly that nothing here is real. */
export function DemoBanner() {
  const { data } = useHealth();
  if (!data?.demo_mode) return null;
  return (
    <div className="flex flex-wrap items-center justify-center gap-x-2 gap-y-1 border-b border-warning/25 bg-warning-soft px-4 py-2 text-center text-[12.5px] text-text-1">
      <FlaskConical className="size-3.5 shrink-0 text-warning" aria-hidden />
      <span>
        <strong className="font-semibold">Live demo with a fictional candidate and sample jobs.</strong> Your changes stay in
        your browser session for two hours. Uploads, discovery and auto-apply runs are off here.
      </span>
      <a
        href={REPO_URL}
        target="_blank"
        rel="noreferrer"
        className="font-medium text-warning underline underline-offset-2 hover:no-underline"
      >
        Run it for your own search
      </a>
    </div>
  );
}
