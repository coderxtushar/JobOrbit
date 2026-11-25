"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BadgeCheck, CircleSlash, ImageOff, Loader2, RefreshCw, ShieldQuestion } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { ErrorState, errorMessage } from "@/components/shared/query-state";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import type { Schemas } from "@/lib/api/client";
import { api } from "@/lib/api/endpoints";
import { formatDateTime, humanize } from "@/lib/formatting";
import { cn } from "@/lib/utils";

type Detail = Schemas["SubmissionAttemptDetail"];

export const UNCLEAR_STATES = new Set(["outcome_unknown", "requires_user_action"]);

function show(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

/** What was sent, what happened, and — for an unclear outcome — how to settle it. */
export function AttemptDetail({ attemptId }: { attemptId: number }) {
  const query = useQuery({
    queryKey: ["autoapply", "attempt", attemptId],
    queryFn: () => api.attempt(attemptId),
  });

  if (query.isPending) {
    return (
      <div className="space-y-2 p-4">
        <Skeleton className="h-4 w-1/3" />
        <Skeleton className="h-16 w-full" />
      </div>
    );
  }
  if (query.isError) {
    return (
      <div className="p-4">
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      </div>
    );
  }
  const detail = query.data;
  const answers = Object.entries((detail.answers_sent ?? {}) as Record<string, unknown>);
  const artifacts = Object.entries((detail.artifacts ?? {}) as Record<string, unknown>);
  const events = detail.events ?? [];

  return (
    <div className="space-y-4 border-t border-line bg-surface-2/20 px-4 pb-4 pt-3.5">
      {detail.confirmation_evidence ? (
        <div className="flex items-start gap-2 rounded-lg border border-success/25 bg-success-soft px-3 py-2 text-xs text-text-1">
          <BadgeCheck className="mt-0.5 size-3.5 shrink-0 text-success" />
          <span>
            <span className="font-semibold">Confirmation evidence:</span> {detail.confirmation_evidence}
            {detail.confirmation_id ? <span className="text-text-3"> · reference {detail.confirmation_id}</span> : null}
          </span>
        </div>
      ) : null}
      {detail.detail ? <p className="text-xs leading-relaxed text-text-2">{detail.detail}</p> : null}

      {UNCLEAR_STATES.has(detail.state) ? <Resolve detail={detail} /> : null}

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="space-y-4">
          <div>
            <h4 className="mb-1.5 text-xs font-semibold text-text-1">Answers typed into the form</h4>
            {answers.length ? (
              <div className="overflow-hidden rounded-lg border border-line">
                <Table>
                  <TableHeader>
                    <TableRow className="border-line hover:bg-transparent">
                      <TableHead className="h-8 bg-surface-2/50 text-[11px] text-text-3">Question</TableHead>
                      <TableHead className="h-8 bg-surface-2/50 text-[11px] text-text-3">Answer</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {answers.map(([question, answer]) => (
                      <TableRow key={question} className="border-line">
                        <TableCell className="max-w-[16rem] whitespace-normal py-1.5 text-xs text-text-2">{question}</TableCell>
                        <TableCell className="max-w-[16rem] whitespace-normal break-words py-1.5 text-xs text-text-1">
                          {show(answer)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            ) : (
              <p className="text-xs text-text-3">No answers were typed into a form for this attempt.</p>
            )}
          </div>

          <div>
            <h4 className="mb-1.5 text-xs font-semibold text-text-1">Artifacts</h4>
            {artifacts.length ? (
              <dl className="grid gap-1 text-xs">
                {artifacts.map(([key, value]) => (
                  <div key={key} className="flex gap-2">
                    <dt className="w-32 shrink-0 text-text-3">{humanize(key)}</dt>
                    <dd className="min-w-0 break-all font-mono text-[11px] text-text-1">{show(value)}</dd>
                  </div>
                ))}
              </dl>
            ) : (
              <p className="text-xs text-text-3">None recorded.</p>
            )}
            {detail.resume_sha256 ? (
              <p className="mt-1 text-[11px] text-text-3">
                Resume sha256 <span className="font-mono">{detail.resume_sha256.slice(0, 16)}…</span>
              </p>
            ) : null}
          </div>

          {detail.has_evidence ? <Evidence attemptId={detail.id} /> : null}
        </div>

        <div>
          <h4 className="mb-1.5 text-xs font-semibold text-text-1">Timeline</h4>
          {events.length ? (
            <ol className="relative space-y-2.5 border-l border-line pl-4">
              {events.map((event) => (
                <li key={event.id} className="relative text-xs">
                  <span
                    className={cn(
                      "absolute -left-[21px] top-1 size-2 rounded-full ring-2 ring-surface-1",
                      event.kind === "error" || event.kind === "failure" ? "bg-danger" : "bg-violet",
                    )}
                  />
                  <p className="text-text-1">
                    <span className="font-medium">{humanize(event.name)}</span>
                    <span className="text-text-3"> · {event.kind}</span>
                  </p>
                  {event.detail ? <p className="text-text-2">{event.detail}</p> : null}
                  <p className="text-[11px] text-text-3">{formatDateTime(event.created_at)}</p>
                </li>
              ))}
            </ol>
          ) : (
            <p className="text-xs text-text-3">No events recorded.</p>
          )}
        </div>
      </div>
    </div>
  );
}

function Evidence({ attemptId }: { attemptId: number }) {
  const [failed, setFailed] = useState(false);
  return (
    <div>
      <h4 className="mb-1.5 text-xs font-semibold text-text-1">Evidence screenshot</h4>
      {failed ? (
        <p className="flex items-center gap-1.5 text-xs text-text-3">
          <ImageOff className="size-3.5" /> The screenshot is no longer kept (its retention period passed).
        </p>
      ) : (
        <a href={api.attemptEvidenceUrl(attemptId)} target="_blank" rel="noreferrer" className="block">
          {/* Served privately through the same-origin proxy; next/image would cache it. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={api.attemptEvidenceUrl(attemptId)}
            alt={`Screenshot taken during attempt ${attemptId}`}
            loading="lazy"
            onError={() => setFailed(true)}
            className="max-h-80 w-full rounded-lg border border-line object-contain object-top"
          />
        </a>
      )}
      <p className="mt-1 text-[11px] text-text-3">Private: served only through this dashboard.</p>
    </div>
  );
}

/**
 * Settling an unclear outcome. JobOrbit never presses Submit again on one, because a retry
 * could send a second application; the user checks and records what they found.
 */
function Resolve({ detail }: { detail: Detail }) {
  const queryClient = useQueryClient();
  const [evidence, setEvidence] = useState("");

  const settle = (next: Detail) => {
    queryClient.setQueryData(["autoapply", "attempt", next.id], next);
    void queryClient.invalidateQueries({ queryKey: ["autoapply", "runs"] });
    void queryClient.invalidateQueries({ queryKey: ["applications"] });
    void queryClient.invalidateQueries({ queryKey: ["nav"] });
  };

  const recheck = useMutation({
    mutationFn: () => api.recheckAttempt(detail.id),
    onSuccess: (next) => {
      settle(next);
      if (UNCLEAR_STATES.has(next.state)) toast.info("Still unclear", { description: "No confirmation was found." });
      else toast.success(`Now: ${humanize(next.state)}`);
    },
    onError: (error) => toast.error("Recheck failed", { description: errorMessage(error) }),
  });
  const resolve = useMutation({
    mutationFn: (outcome: "submitted" | "not_submitted") =>
      api.resolveAttempt(detail.id, { outcome, evidence: evidence.trim() }),
    onSuccess: (next, outcome) => {
      settle(next);
      toast.success(outcome === "submitted" ? "Recorded as submitted" : "Recorded as not submitted");
    },
    onError: (error) => toast.error("Could not record that", { description: errorMessage(error) }),
  });
  const busy = recheck.isPending || resolve.isPending;
  const enough = evidence.trim().length >= 4;
  const evidenceId = `resolve-evidence-${detail.id}`;

  return (
    <div className="space-y-3 rounded-xl border border-warning/30 bg-warning-soft p-3.5">
      <div className="flex items-start gap-2.5">
        <ShieldQuestion className="mt-0.5 size-4 shrink-0 text-warning" />
        <div className="text-xs leading-relaxed text-text-1">
          <p className="font-semibold">Settle this outcome</p>
          <p className="text-text-2">
            An unclear outcome is never retried automatically: pressing Submit again could send a second
            application. Recheck looks at the page left open and any linked confirmation email without resubmitting.
            Otherwise check the employer&apos;s page or your inbox, then record what you found.
          </p>
        </div>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor={evidenceId} className="text-xs text-text-2">
          What showed it was submitted (email subject, reference number) — needed for “It was submitted”
        </Label>
        <Textarea
          id={evidenceId}
          value={evidence}
          maxLength={1000}
          onChange={(event) => setEvidence(event.target.value)}
          placeholder="e.g. “Thanks for applying to Acme” email, 25 Nov"
          className="min-h-14 bg-surface-1"
        />
      </div>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="outline" disabled={busy} onClick={() => recheck.mutate()}>
          {recheck.isPending ? <Loader2 className="animate-spin" /> : <RefreshCw />} Recheck
        </Button>
        <Button
          size="sm"
          disabled={busy || !enough}
          title={enough ? undefined : "Describe the evidence first (at least 4 characters)"}
          onClick={() => resolve.mutate("submitted")}
        >
          <BadgeCheck /> It was submitted
        </Button>
        <Button size="sm" variant="ghost" disabled={busy} onClick={() => resolve.mutate("not_submitted")}>
          <CircleSlash /> It was not submitted
        </Button>
      </div>
      {resolve.isError ? <p role="alert" className="text-xs text-danger">{errorMessage(resolve.error)}</p> : null}
    </div>
  );
}
