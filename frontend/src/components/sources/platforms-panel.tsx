"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, Check, ChevronRight, X } from "lucide-react";
import { useState } from "react";

import { ErrorState } from "@/components/shared/query-state";
import { StateBadge, StatusBadge } from "@/components/shared/status-badge";
import { Surface } from "@/components/shared/surface";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import type { Schemas } from "@/lib/api/client";
import { api } from "@/lib/api/endpoints";
import { APPLICATION_STATUS } from "@/lib/constants/states";
import { formatNumber, formatRelative, humanize } from "@/lib/formatting";
import { cn } from "@/lib/utils";

type Platform = Schemas["PlatformSummary"];

export function PlatformsPanel() {
  const platforms = useQuery({ queryKey: ["sources", "platforms"], queryFn: api.platforms });
  const [openKey, setOpenKey] = useState<string | null>(null);

  if (platforms.isError) return <ErrorState error={platforms.error} onRetry={() => platforms.refetch()} />;
  return (
    <>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {platforms.isLoading
          ? Array.from({ length: 5 }, (_, index) => <Skeleton key={index} className="h-40 rounded-xl" />)
          : platforms.data?.map((platform) => (
              <PlatformCard key={platform.key} platform={platform} onOpen={() => setOpenKey(platform.key)} />
            ))}
      </div>
      <Sheet open={openKey !== null} onOpenChange={(open) => (open ? null : setOpenKey(null))}>
        <SheetContent className="w-full gap-0 overflow-y-auto p-0 sm:max-w-lg">
          {openKey ? <PlatformDetail platformKey={openKey} /> : null}
        </SheetContent>
      </Sheet>
    </>
  );
}

function PlatformCard({ platform, onOpen }: { platform: Platform; onOpen: () => void }) {
  return (
    <Surface interactive className="group flex flex-col p-4">
      <button
        type="button"
        onClick={onOpen}
        className="flex h-full flex-col text-left outline-none focus-visible:rounded-md focus-visible:ring-2 focus-visible:ring-ring"
      >
        <div className="flex items-start justify-between gap-2">
          <p className="font-heading text-sm font-semibold text-text-1">{platform.display_name}</p>
          <ChevronRight className="size-4 shrink-0 text-text-3 transition-transform group-hover:translate-x-0.5 group-hover:text-text-1" />
        </div>
        <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-text-3">{platform.tagline}</p>
        <div className="mt-3 flex flex-wrap gap-1.5">
          <StatusBadge tone={platform.supports_automated_discovery ? "cyan" : "neutral"}>
            {platform.supports_automated_discovery ? "Automated discovery" : "Import only"}
          </StatusBadge>
          {platform.supports_automated_submission ? <StatusBadge tone="violet">Auto-apply</StatusBadge> : null}
        </div>
        <dl className="mt-auto grid grid-cols-2 gap-2 pt-3 text-xs">
          <div>
            <dt className="text-text-3">Listings</dt>
            <dd className="font-medium text-text-1 tabular">{formatNumber(platform.jobs_stored)}</dd>
          </div>
          <div>
            <dt className="text-text-3">Applications</dt>
            <dd className="font-medium text-text-1 tabular">{formatNumber(platform.applications)}</dd>
          </div>
        </dl>
      </button>
    </Surface>
  );
}

function PlatformDetail({ platformKey }: { platformKey: string }) {
  const detail = useQuery({
    queryKey: ["sources", "platform", platformKey],
    queryFn: () => api.platform(platformKey),
  });
  const data = detail.data;

  return (
    <>
      <SheetHeader className="border-b border-line p-5">
        <SheetTitle className="font-heading text-lg">{data?.display_name ?? "Platform"}</SheetTitle>
        <SheetDescription>{data?.tagline ?? "What this platform permits."}</SheetDescription>
        {data?.homepage ? (
          <a
            href={data.homepage}
            target="_blank"
            rel="noreferrer"
            className="inline-flex w-fit items-center gap-1 text-xs text-violet hover:underline"
          >
            {data.homepage.replace(/^https?:\/\//, "")} <ArrowUpRight className="size-3" />
          </a>
        ) : null}
      </SheetHeader>
      <div className="space-y-6 p-5">
        {detail.isLoading ? (
          <div className="space-y-3">
            <Skeleton className="h-20 w-full" />
            <Skeleton className="h-40 w-full" />
          </div>
        ) : detail.isError ? (
          <ErrorState error={detail.error} onRetry={() => detail.refetch()} />
        ) : data ? (
          <>
            <section>
              <h3 className="text-[11px] font-semibold uppercase tracking-wider text-text-3">How jobs arrive</h3>
              <p className="mt-1.5 text-sm leading-relaxed text-text-2">{data.how_jobs_arrive}</p>
              {data.notes.length ? (
                <ul className="mt-2 space-y-1 pl-4 text-xs leading-relaxed text-text-3">
                  {data.notes.map((note) => (
                    <li key={note} className="list-disc">
                      {note}
                    </li>
                  ))}
                </ul>
              ) : null}
            </section>

            <section>
              <h3 className="text-[11px] font-semibold uppercase tracking-wider text-text-3">What JobOrbit can do here</h3>
              <ul className="mt-2 space-y-2">
                {data.actions.map((action) => (
                  <li key={action.key} className="flex items-start gap-2.5">
                    <span
                      className={cn(
                        "mt-0.5 grid size-5 shrink-0 place-items-center rounded-full ring-1 ring-inset",
                        action.available
                          ? "bg-success-soft text-success ring-success/25"
                          : "bg-surface-3 text-text-3 ring-line-strong",
                      )}
                    >
                      {action.available ? <Check className="size-3" /> : <X className="size-3" />}
                    </span>
                    <div>
                      <p className={cn("text-sm", action.available ? "text-text-1" : "text-text-3")}>{action.label}</p>
                      <p className="text-xs leading-relaxed text-text-3">{action.description}</p>
                    </div>
                  </li>
                ))}
              </ul>
            </section>

            <section>
              <h3 className="text-[11px] font-semibold uppercase tracking-wider text-text-3">
                Sources ({data.sources.length})
              </h3>
              <ul className="mt-2 divide-y divide-line rounded-lg border border-line">
                {data.sources.map((source) => (
                  <li key={source.source} className="space-y-1 p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="text-sm font-medium text-text-1">{source.display_name}</span>
                      <span className="flex items-center gap-1.5">
                        {source.effective_capabilities.authorized_discovery_enabled ? (
                          <StatusBadge tone="cyan">Discovery</StatusBadge>
                        ) : null}
                        <StatusBadge tone={source.enabled ? "success" : "neutral"}>{source.enabled ? "On" : "Off"}</StatusBadge>
                      </span>
                    </div>
                    <p className="text-xs text-text-3">
                      {formatNumber(source.jobs_stored)} listing(s) ·{" "}
                      {source.last_run_at ? `last run ${formatRelative(source.last_run_at)}` : "never run"}
                    </p>
                    {source.last_error ? <p className="text-xs text-danger">{source.last_error}</p> : null}
                  </li>
                ))}
              </ul>
            </section>

            {Object.keys(data.jobs_by_status).length || Object.keys(data.applications_by_status).length ? (
              <section className="grid gap-4 sm:grid-cols-2">
                <div>
                  <h3 className="text-[11px] font-semibold uppercase tracking-wider text-text-3">Listings by status</h3>
                  <ul className="mt-2 space-y-1 text-xs">
                    {Object.entries(data.jobs_by_status).map(([status, count]) => (
                      <li key={status} className="flex justify-between gap-2">
                        <span className="text-text-2">{humanize(status)}</span>
                        <span className="text-text-1 tabular">{formatNumber(count)}</span>
                      </li>
                    ))}
                  </ul>
                </div>
                <div>
                  <h3 className="text-[11px] font-semibold uppercase tracking-wider text-text-3">Applications</h3>
                  <ul className="mt-2 space-y-1.5 text-xs">
                    {Object.entries(data.applications_by_status).length ? (
                      Object.entries(data.applications_by_status).map(([status, count]) => (
                        <li key={status} className="flex items-center justify-between gap-2">
                          <StateBadge value={status} map={APPLICATION_STATUS} />
                          <span className="text-text-1 tabular">{formatNumber(count)}</span>
                        </li>
                      ))
                    ) : (
                      <li className="text-text-3">None yet.</li>
                    )}
                  </ul>
                </div>
              </section>
            ) : null}
          </>
        ) : null}
      </div>
    </>
  );
}
