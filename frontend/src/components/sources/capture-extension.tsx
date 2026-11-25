"use client";

import { useQuery } from "@tanstack/react-query";
import { KeyRound, MousePointerClick, Puzzle } from "lucide-react";

import { SectionHeading } from "@/components/shared/page-header";
import { ErrorState } from "@/components/shared/query-state";
import { StatusBadge } from "@/components/shared/status-badge";
import { Surface } from "@/components/shared/surface";
import { Kbd } from "@/components/ui/kbd";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api/endpoints";

const STEPS: React.ReactNode[] = [
  <>Start the JobOrbit API on this computer (it is running if this page loads).</>,
  <>
    Open <Kbd>chrome://extensions</Kbd> in Chrome, Edge or Brave.
  </>,
  <>
    Turn on <strong className="font-medium text-text-1">Developer mode</strong> (top right).
  </>,
  <>
    Click <strong className="font-medium text-text-1">Load unpacked</strong> and choose the{" "}
    <code className="rounded bg-surface-3 px-1 py-0.5 text-[11px] text-text-1">extension/</code> folder in the
    repository.
  </>,
  <>Optional: pin &ldquo;JobOrbit Capture&rdquo; from the puzzle-piece menu so its button is visible.</>,
  <>
    Optional: in the extension&rsquo;s <strong className="font-medium text-text-1">Options</strong>, set the API address
    (default <code className="text-[11px]">http://127.0.0.1:8000</code>), a token, and this dashboard&rsquo;s address,
    then press <strong className="font-medium text-text-1">Test connection</strong>.
  </>,
];

/**
 * The capture extension sends the listing in the current tab to the local API, for sites
 * with no discovery integration. It runs only when its button is clicked.
 */
export function CaptureExtension() {
  const status = useQuery({ queryKey: ["sources", "capture"], queryFn: api.captureStatus });
  const data = status.data;

  return (
    <Surface className="p-5">
      <SectionHeading
        title="Capture extension"
        description="Save the listing you are looking at on LinkedIn, Naukri, Indeed, Wellfound or a careers page."
        actions={
          status.isLoading ? (
            <Skeleton className="h-5 w-24 rounded-full" />
          ) : data ? (
            <StatusBadge tone={data.capture_enabled ? "success" : "warning"}>
              {data.capture_enabled ? "Accepting captures" : "Capture is off"}
            </StatusBadge>
          ) : null
        }
      />
      {status.isError ? <ErrorState error={status.error} onRetry={() => status.refetch()} className="mb-4" /> : null}
      <div className="grid gap-5 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <div className="space-y-3">
          <dl className="grid grid-cols-2 gap-3 text-xs">
            <div className="rounded-lg border border-line bg-surface-2/40 p-3">
              <dt className="text-text-3">Capture endpoint</dt>
              <dd className="mt-0.5 font-medium text-text-1">
                {status.isLoading ? "…" : data ? (data.capture_enabled ? "Enabled" : "Disabled") : "—"}
              </dd>
            </div>
            <div className="rounded-lg border border-line bg-surface-2/40 p-3">
              <dt className="flex items-center gap-1 text-text-3">
                <KeyRound className="size-3" /> API token
              </dt>
              <dd className="mt-0.5 font-medium text-text-1">
                {status.isLoading ? "…" : data ? (data.token_required ? "Required" : "Not required") : "—"}
              </dd>
            </div>
            <div className="rounded-lg border border-line bg-surface-2/40 p-3">
              <dt className="text-text-3">API version</dt>
              <dd className="mt-0.5 font-medium text-text-1 tabular">{data?.version ?? "—"}</dd>
            </div>
            <div className="rounded-lg border border-line bg-surface-2/40 p-3">
              <dt className="text-text-3">Demo mode</dt>
              <dd className="mt-0.5 font-medium text-text-1">{data ? (data.demo_mode ? "On" : "Off") : "—"}</dd>
            </div>
          </dl>
          {data?.token_required ? (
            <p className="text-xs leading-relaxed text-text-3">
              The API was started with <code className="text-[11px]">JA_API_TOKEN</code>; paste the same value into the
              extension&rsquo;s Options.
            </p>
          ) : null}
          <div className="flex items-start gap-2.5 rounded-lg bg-violet-soft p-3 text-xs leading-relaxed text-text-2">
            <MousePointerClick className="mt-0.5 size-4 shrink-0 text-violet" />
            <p>
              It runs only when you click its button, reads only that tab, never reads form fields or cookies, and never
              applies to a job. You review every field before it is sent.
            </p>
          </div>
        </div>
        <div>
          <p className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-text-3">
            <Puzzle className="size-3.5" /> Install (load unpacked)
          </p>
          <ol className="space-y-2">
            {STEPS.map((step, index) => (
              <li key={index} className="flex gap-3 text-xs leading-relaxed text-text-2">
                <span className="grid size-5 shrink-0 place-items-center rounded-full bg-surface-3 text-[10.5px] font-semibold text-text-1 tabular">
                  {index + 1}
                </span>
                <span className="pt-0.5">{step}</span>
              </li>
            ))}
          </ol>
          <p className="mt-3 text-[11.5px] text-text-3">
            Full details, including exactly what it can and cannot access, are in{" "}
            <code className="text-[11px]">extension/README.md</code>.
          </p>
        </div>
      </div>
    </Surface>
  );
}
