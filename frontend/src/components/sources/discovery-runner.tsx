"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { motion } from "motion/react";
import { Loader2, Radar, X } from "lucide-react";
import { toast } from "sonner";

import { errorMessage } from "@/components/shared/query-state";
import { Button } from "@/components/ui/button";
import type { Schemas } from "@/lib/api/client";
import { api } from "@/lib/api/endpoints";
import { formatNumber } from "@/lib/formatting";

import { ImportSummaryCard } from "./import-summary";
import { canDiscover } from "./source-list";

/**
 * Runs discovery for the sources ticked in the list. Each source answers on its own: a
 * source whose feed is switched off in .env reports "skipped" with the reason rather than
 * failing silently.
 */
export function DiscoveryRunner({
  sources,
  selected,
  onSelectedChange,
}: {
  sources: Schemas["SourceRead"][];
  selected: string[];
  onSelectedChange: (next: string[]) => void;
}) {
  const queryClient = useQueryClient();
  const discoverable = sources.filter(canDiscover);
  const chosen = selected.filter((key) => discoverable.some((item) => item.source === key));

  const run = useMutation({
    mutationFn: (keys: Schemas["SourceName"][]) => api.discoverJobs({ sources: keys, trigger: "manual" }),
    onSuccess: (summaries) => {
      const created = summaries.reduce((sum, item) => sum + item.jobs_created, 0);
      toast.success("Discovery finished", {
        description: `${formatNumber(created)} new listing(s) across ${summaries.length} source(s).`,
      });
      void queryClient.invalidateQueries({ queryKey: ["sources"] });
      void queryClient.invalidateQueries({ queryKey: ["analytics"] });
      void queryClient.invalidateQueries({ queryKey: ["logs"] });
    },
    onError: (error) => toast.error("Discovery did not run", { description: errorMessage(error) }),
  });

  const nameOf = (key: string) => sources.find((item) => item.source === key)?.display_name ?? key;

  return (
    <div className="space-y-3">
      <div className="flex flex-col gap-3 rounded-xl border border-line bg-surface-2/40 p-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-cyan-soft text-cyan ring-1 ring-inset ring-cyan/20">
            <Radar className="size-4" />
          </span>
          <div>
            <p className="text-sm font-medium text-text-1">
              {chosen.length
                ? `${chosen.length} of ${discoverable.length} discovery source(s) selected`
                : discoverable.length
                  ? "Tick the sources to search"
                  : "No source can run discovery right now"}
            </p>
            <p className="text-xs text-text-3">
              {discoverable.length
                ? "Only sources that are on and publish an interface for it can be ticked."
                : "Turn on a source with automated discovery, or import a file below."}
            </p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {discoverable.length ? (
            <Button
              variant="ghost"
              size="sm"
              onClick={() =>
                onSelectedChange(chosen.length === discoverable.length ? [] : discoverable.map((item) => item.source))
              }
            >
              {chosen.length === discoverable.length ? "Clear" : "Select all"}
            </Button>
          ) : null}
          <Button
            size="sm"
            disabled={!chosen.length || run.isPending}
            onClick={() => run.mutate(chosen as Schemas["SourceName"][])}
            className="shadow-glow"
          >
            {run.isPending ? <Loader2 className="animate-spin" /> : <Radar />}
            {run.isPending ? "Running…" : "Run discovery"}
          </Button>
        </div>
      </div>

      {run.isPending ? (
        <p className="flex items-center gap-2 px-1 text-xs text-text-3">
          <Loader2 className="size-3.5 animate-spin" /> Asking {chosen.map(nameOf).join(", ")}. Large boards can take a
          minute.
        </p>
      ) : null}

      {run.data ? (
        <motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} className="space-y-2">
          <div className="flex items-center justify-between px-1">
            <p className="text-xs font-semibold uppercase tracking-wider text-text-3">Results of this run</p>
            <Button variant="ghost" size="icon-xs" aria-label="Dismiss results" onClick={() => run.reset()}>
              <X />
            </Button>
          </div>
          {run.data.length ? (
            <div className="grid gap-2 md:grid-cols-2">
              {run.data.map((summary) => (
                <ImportSummaryCard key={summary.import_run_id} summary={summary} displayName={nameOf(summary.source)} />
              ))}
            </div>
          ) : (
            <p className="px-1 text-xs text-text-3">No selected source was enabled, so nothing ran.</p>
          )}
        </motion.div>
      ) : null}
    </div>
  );
}
