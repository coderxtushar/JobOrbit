"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "motion/react";
import { AlertTriangle, ChevronDown, Lock, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { errorMessage } from "@/components/shared/query-state";
import { StatusBadge } from "@/components/shared/status-badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { Schemas } from "@/lib/api/client";
import { api } from "@/lib/api/endpoints";
import { formatRelative } from "@/lib/formatting";
import { cn } from "@/lib/utils";

type Source = Schemas["SourceRead"];
type CapabilityKey = "manual_import_enabled" | "authorized_discovery_enabled" | "browser_assistance_enabled";

const CAPABILITIES: { key: CapabilityKey; label: string; help: string }[] = [
  { key: "manual_import_enabled", label: "Manual import", help: "Files and pasted listings you bring yourself." },
  {
    key: "authorized_discovery_enabled",
    label: "Automated discovery",
    help: "Fetches new listings through the platform's published interface.",
  },
  {
    key: "browser_assistance_enabled",
    label: "Browser assistance",
    help: "Opens listings in your own browser so you act there.",
  },
];

/** A source can be run by "Run discovery" when it is on and discovery is effectively allowed. */
export function canDiscover(source: Source): boolean {
  return source.enabled && source.effective_capabilities.authorized_discovery_enabled;
}

function useSourceUpdate() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ source, body }: { source: Source["source"]; body: Schemas["SourceUpdate"] }) =>
      api.updateSource(source, body),
    onSuccess: (updated) => {
      queryClient.setQueryData<Source[]>(["sources"], (current) =>
        current?.map((item) => (item.source === updated.source ? updated : item)),
      );
      void queryClient.invalidateQueries({ queryKey: ["logs", "diagnostics"] });
      toast.success(`${updated.display_name} updated`);
    },
    onError: (error) => toast.error("The source was not changed", { description: errorMessage(error) }),
  });
}

export function SourceList({
  sources,
  selected,
  onSelectedChange,
}: {
  sources: Source[];
  selected: string[];
  onSelectedChange: (next: string[]) => void;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const update = useSourceUpdate();
  const pendingFor = update.isPending ? update.variables?.source : undefined;

  return (
    <ul className="divide-y divide-line">
      {sources.map((source) => {
        const discoverable = canDiscover(source);
        const expanded = open === source.source;
        const failing = source.consecutive_failures > 0 || Boolean(source.last_error);
        const notUsable = source.status_detail.startsWith("Not usable");
        return (
          <li key={source.source} className="group/row">
            <div className="flex items-start gap-3 px-4 py-3.5 transition-colors hover:bg-surface-2/40">
              <div className="pt-0.5">
                {discoverable ? (
                  <Checkbox
                    aria-label={`Include ${source.display_name} in the next discovery run`}
                    checked={selected.includes(source.source)}
                    onCheckedChange={(checked) =>
                      onSelectedChange(
                        checked
                          ? [...selected, source.source]
                          : selected.filter((item) => item !== source.source),
                      )
                    }
                  />
                ) : (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <span tabIndex={0} className="grid size-4 place-items-center text-text-3" aria-label="No automated discovery">
                        <Lock className="size-3.5" />
                      </span>
                    </TooltipTrigger>
                    <TooltipContent className="max-w-64">
                      {source.enabled
                        ? "Not available for automated discovery. Import a file instead."
                        : "Turn this source on to use it."}
                    </TooltipContent>
                  </Tooltip>
                )}
              </div>
              <button
                type="button"
                onClick={() => setOpen(expanded ? null : source.source)}
                aria-expanded={expanded}
                className="min-w-0 flex-1 rounded-md text-left outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className={cn("text-sm font-medium", source.enabled ? "text-text-1" : "text-text-3")}>
                    {source.display_name}
                  </span>
                  {source.capabilities.authorized_discovery_enabled ? (
                    <StatusBadge tone={source.effective_capabilities.authorized_discovery_enabled ? "cyan" : "neutral"}>
                      Discovery
                    </StatusBadge>
                  ) : (
                    <StatusBadge tone="neutral" dot={false}>
                      Import only
                    </StatusBadge>
                  )}
                  {!source.enabled ? <StatusBadge tone="neutral">Off</StatusBadge> : null}
                  {failing ? (
                    <StatusBadge tone="danger">
                      {source.consecutive_failures
                        ? `${source.consecutive_failures} failure${source.consecutive_failures === 1 ? "" : "s"}`
                        : "Last run failed"}
                    </StatusBadge>
                  ) : null}
                </div>
                <p className={cn("mt-0.5 line-clamp-1 text-xs", notUsable ? "text-warning" : "text-text-3")}>
                  {source.status_detail || source.policy_basis}
                </p>
              </button>
              <div className="flex shrink-0 items-center gap-2 pt-0.5">
                <span className="hidden text-[11px] text-text-3 sm:inline">
                  {source.last_run_at ? `Ran ${formatRelative(source.last_run_at)}` : "Never run"}
                </span>
                <Switch
                  aria-label={`${source.enabled ? "Turn off" : "Turn on"} ${source.display_name}`}
                  checked={source.enabled}
                  disabled={pendingFor === source.source}
                  onCheckedChange={(enabled) => update.mutate({ source: source.source, body: { enabled } })}
                />
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={expanded ? "Hide details" : "Show details"}
                  onClick={() => setOpen(expanded ? null : source.source)}
                >
                  <ChevronDown className={cn("transition-transform duration-200", expanded && "rotate-180")} />
                </Button>
              </div>
            </div>
            <AnimatePresence initial={false}>
              {expanded ? (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: "auto", opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
                  className="overflow-hidden"
                >
                  <SourceDetail
                    source={source}
                    pending={pendingFor === source.source}
                    onUpdate={(body) => update.mutate({ source: source.source, body })}
                  />
                </motion.div>
              ) : null}
            </AnimatePresence>
          </li>
        );
      })}
    </ul>
  );
}

function SourceDetail({
  source,
  pending,
  onUpdate,
}: {
  source: Source;
  pending: boolean;
  onUpdate: (body: Schemas["SourceUpdate"]) => void;
}) {
  const [rate, setRate] = useState(String(source.rate_limit_per_hour));
  const rateNumber = Number(rate);
  const rateValid = Number.isInteger(rateNumber) && rateNumber >= 1 && rateNumber <= 1000;

  return (
    <div className="space-y-4 border-t border-line bg-surface-2/30 px-4 py-4 sm:pl-11">
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        {CAPABILITIES.map((capability) => {
          const declared = source.capabilities[capability.key];
          const effective = source.effective_capabilities[capability.key];
          const id = `${source.source}-${capability.key}`;
          return (
            <div key={capability.key} className="flex items-start justify-between gap-3 rounded-lg border border-line bg-surface-1 p-3">
              <div className="min-w-0">
                <Label htmlFor={id} className="text-xs font-medium text-text-1">
                  {capability.label}
                </Label>
                <p className="mt-0.5 text-[11px] leading-snug text-text-3">
                  {declared ? capability.help : "Not permitted for this source."}
                </p>
              </div>
              <Switch
                id={id}
                size="sm"
                checked={effective}
                disabled={!declared || pending}
                onCheckedChange={(checked) => onUpdate({ [capability.key]: checked })}
              />
            </div>
          );
        })}
        <div className="flex items-start justify-between gap-3 rounded-lg border border-line bg-surface-1 p-3">
          <div className="min-w-0">
            <p className="text-xs font-medium text-text-1">Automated submission</p>
            <p className="mt-0.5 text-[11px] leading-snug text-text-3">
              Never enabled for a source. Auto-apply has its own controls.
            </p>
          </div>
          <Lock className="mt-0.5 size-3.5 shrink-0 text-text-3" />
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <div className="space-y-3">
          <div>
            <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-text-3">
              <ShieldCheck className="size-3.5" /> Compliance basis
            </p>
            <p className="mt-1 text-xs leading-relaxed text-text-2">{source.policy_basis}</p>
          </div>
          {source.limitations?.length ? (
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wider text-text-3">Limitations</p>
              <ul className="mt-1 space-y-1 pl-4 text-xs leading-relaxed text-text-2">
                {source.limitations.map((limitation) => (
                  <li key={limitation} className="list-disc">
                    {limitation}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
        <div className="space-y-3">
          <dl className="grid grid-cols-2 gap-3 text-xs">
            <div>
              <dt className="text-text-3">Last run</dt>
              <dd className="text-text-1">{source.last_run_at ? formatRelative(source.last_run_at) : "Never"}</dd>
            </div>
            <div>
              <dt className="text-text-3">Consecutive failures</dt>
              <dd className={source.consecutive_failures ? "text-danger tabular" : "text-text-1 tabular"}>
                {source.consecutive_failures}
              </dd>
            </div>
          </dl>
          {source.last_error ? (
            <p className="flex items-start gap-2 rounded-lg bg-danger-soft p-2.5 text-xs text-text-1">
              <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-danger" />
              {source.last_error}
            </p>
          ) : null}
          <form
            className="flex items-end gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              if (rateValid) onUpdate({ rate_limit_per_hour: rateNumber });
            }}
          >
            <div className="flex-1 space-y-1">
              <Label htmlFor={`${source.source}-rate`} className="text-xs text-text-2">
                Runs per hour (1–1000)
              </Label>
              <Input
                id={`${source.source}-rate`}
                type="number"
                min={1}
                max={1000}
                inputMode="numeric"
                value={rate}
                onChange={(event) => setRate(event.target.value)}
                aria-invalid={!rateValid}
                className="h-8"
              />
            </div>
            <Button
              type="submit"
              size="sm"
              variant="outline"
              className="h-8"
              disabled={!rateValid || pending || rateNumber === source.rate_limit_per_hour}
            >
              Save
            </Button>
          </form>
        </div>
      </div>
    </div>
  );
}
