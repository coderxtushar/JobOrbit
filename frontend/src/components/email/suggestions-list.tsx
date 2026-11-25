"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Ban, Check, Lightbulb, Loader2, X } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useState } from "react";
import { toast } from "sonner";

import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState, errorMessage } from "@/components/shared/query-state";
import { StateBadge, StatusBadge } from "@/components/shared/status-badge";
import { Surface } from "@/components/shared/surface";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api/client";
import type { Schemas } from "@/lib/api/client";
import { api } from "@/lib/api/endpoints";
import { APPLICATION_STATUS, OUTCOME } from "@/lib/constants/states";
import { formatDateTime, formatRelative } from "@/lib/formatting";

import { fieldLabel, percent } from "./labels";

type Suggestion = Schemas["StatusSuggestionRead"];

/** Pending status/outcome changes proposed from email. Each needs an explicit Accept. */
export function SuggestionsList() {
  const suggestions = useQuery({
    queryKey: ["email", "suggestions", "pending"],
    queryFn: () => api.suggestions("pending", 100),
  });
  const reduced = useReducedMotion();

  if (suggestions.isLoading) {
    return (
      <div className="space-y-3">
        {Array.from({ length: 2 }).map((_, index) => (
          <Skeleton key={index} className="h-36 w-full rounded-xl" />
        ))}
      </div>
    );
  }
  if (suggestions.isError) return <ErrorState error={suggestions.error} onRetry={() => suggestions.refetch()} />;

  const items = suggestions.data ?? [];
  if (!items.length) {
    return (
      <EmptyState
        icon={Lightbulb}
        title="No pending suggestions"
        description="When an email confirms, rejects, invites or offers, a suggested change appears here. Nothing on an application changes until you accept it."
      />
    );
  }

  return (
    <ul className="space-y-3">
      <AnimatePresence initial={false}>
        {items.map((suggestion) => (
          <motion.li
            key={suggestion.id}
            layout={!reduced}
            initial={reduced ? false : { opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={reduced ? { opacity: 0 } : { opacity: 0, x: 12 }}
            transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
          >
            <SuggestionCard suggestion={suggestion} />
          </motion.li>
        ))}
      </AnimatePresence>
    </ul>
  );
}

function SuggestionCard({ suggestion }: { suggestion: Suggestion }) {
  const queryClient = useQueryClient();
  const [refusal, setRefusal] = useState<string | null>(null);
  const isStatus = suggestion.field === "status";
  const map = isStatus ? APPLICATION_STATUS : OUTCOME;
  const current = isStatus ? suggestion.current_status : suggestion.current_outcome;

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["email"] });
    void queryClient.invalidateQueries({ queryKey: ["applications"] });
    void queryClient.invalidateQueries({ queryKey: ["nav"] });
  };

  const accept = useMutation({
    mutationFn: () => api.acceptSuggestion(suggestion.id),
    onSuccess: (decision) => {
      setRefusal(null);
      toast.success(decision.message || "Suggestion accepted", {
        description: decision.changes?.length ? decision.changes.join(" · ") : undefined,
      });
      refresh();
    },
    onError: (failure) => {
      if (failure instanceof ApiError && failure.code === "suggestion_not_applicable") {
        setRefusal(failure.message);
      } else {
        toast.error("Could not accept the suggestion", { description: errorMessage(failure) });
      }
    },
  });

  const dismiss = useMutation({
    mutationFn: () => api.dismissSuggestion(suggestion.id),
    onSuccess: () => {
      toast.success("Suggestion dismissed", { description: "The application was not changed." });
      refresh();
    },
    onError: (failure) => toast.error("Could not dismiss the suggestion", { description: errorMessage(failure) }),
  });

  const busy = accept.isPending || dismiss.isPending;

  return (
    <Surface className="space-y-3 p-4 transition-colors hover:border-line-strong sm:p-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0 space-y-1">
          <p className="font-medium text-text-1">
            {suggestion.job_title || `Application #${suggestion.application_id}`}
            {suggestion.job_company ? <span className="font-normal text-text-2"> · {suggestion.job_company}</span> : null}
          </p>
          <p className="text-xs text-text-3">
            Application #{suggestion.application_id}
            <span title={formatDateTime(suggestion.created_at)}> · suggested {formatRelative(suggestion.created_at)}</span>
            {" · "}confidence {percent(suggestion.confidence)}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2 text-xs">
          <span className="text-text-3">{fieldLabel(suggestion.field)}</span>
          {current ? <StateBadge value={current} map={map} /> : <span className="text-text-3">—</span>}
          <ArrowRight className="size-3.5 text-text-3" />
          <StateBadge value={suggestion.suggested_value} map={map} />
        </div>
      </div>
      {suggestion.reason ? <p className="text-xs leading-relaxed text-text-2">{suggestion.reason}</p> : null}

      {refusal ? (
        <div role="alert" className="flex gap-2 rounded-lg border border-warning/30 bg-warning-soft px-3 py-2 text-xs leading-relaxed text-text-1">
          <Ban className="mt-0.5 size-3.5 shrink-0 text-warning" />
          <span>
            <span className="font-medium">Refused, and still pending.</span> {refusal}
          </span>
        </div>
      ) : null}

      <div className="flex flex-wrap items-center justify-between gap-2">
        <StatusBadge tone="neutral" dot={false}>
          Not applied until you accept
        </StatusBadge>
        <div className="flex gap-2">
          <Button variant="ghost" size="sm" onClick={() => dismiss.mutate()} disabled={busy}>
            {dismiss.isPending ? <Loader2 className="animate-spin" /> : <X />}
            Dismiss
          </Button>
          <Button size="sm" onClick={() => accept.mutate()} disabled={busy}>
            {accept.isPending ? <Loader2 className="animate-spin" /> : <Check />}
            Accept
          </Button>
        </div>
      </div>
    </Surface>
  );
}
