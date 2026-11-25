"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ClipboardPaste, FileUp, Loader2, ScanSearch } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useId, useRef, useState } from "react";

import { errorMessage } from "@/components/shared/query-state";
import { StatusBadge } from "@/components/shared/status-badge";
import { Surface } from "@/components/shared/surface";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api/endpoints";
import type { Schemas } from "@/lib/api/client";

import { INGEST_OUTCOME, MATCH_STATE, categoryLabel, fieldLabel, percent } from "./labels";

const MAX_BYTES = 5 * 1024 * 1024;

/** Paste or load one raw email; it goes through the same classifier and matcher as a sync. */
export function IngestPanel() {
  const queryClient = useQueryClient();
  const fieldId = useId();
  const fileRef = useRef<HTMLInputElement>(null);
  const [raw, setRaw] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Schemas["EmailIngestResponse"] | null>(null);
  const reduced = useReducedMotion();

  const ingest = useMutation({
    mutationFn: (text: string) => api.ingestEmail({ raw: text }),
    onSuccess: (response) => {
      setError(null);
      setResult(response);
      void queryClient.invalidateQueries({ queryKey: ["email"] });
    },
    onError: (failure) => {
      setResult(null);
      setError(errorMessage(failure));
    },
  });

  const loadFile = async (file: File | undefined) => {
    if (!file) return;
    if (file.size > MAX_BYTES) {
      setError("That file is larger than 5 MB, the most one email can be.");
      return;
    }
    setRaw(await file.text());
    setError(null);
  };

  return (
    <Surface className="p-5 sm:p-6">
      <div className="mb-4 flex items-start gap-3">
        <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-cyan-soft text-cyan ring-1 ring-inset ring-cyan/20">
          <ClipboardPaste className="size-4" />
        </span>
        <div className="space-y-1">
          <h2 className="font-heading text-[15px] font-semibold text-text-1">Paste an email</h2>
          <p className="text-xs leading-relaxed text-text-3">
            Works without connecting Gmail. In Gmail use <span className="text-text-2">⋮ → Show original</span> and copy
            everything, or load a saved <code className="font-mono">.eml</code> file. Only a redacted snippet and the
            extracted facts are stored; the body is not.
          </p>
        </div>
      </div>

      <form
        className="space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (!raw.trim()) {
            setError("Paste the raw email source first.");
            return;
          }
          ingest.mutate(raw);
        }}
      >
        <div className="space-y-1.5">
          <Label htmlFor={`${fieldId}-raw`} className="text-xs text-text-2">
            Raw email source
          </Label>
          <Textarea
            id={`${fieldId}-raw`}
            value={raw}
            onChange={(event) => {
              setRaw(event.target.value);
              if (error) setError(null);
            }}
            rows={8}
            spellCheck={false}
            placeholder={"From: Recruiting <no-reply@greenhouse.io>\nSubject: Thank you for applying\n\n…"}
            className="max-h-80 min-h-40 font-mono text-[12px] leading-relaxed"
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? `${fieldId}-error` : undefined}
          />
          {error ? (
            <p id={`${fieldId}-error`} role="alert" className="text-xs text-danger">
              {error}
            </p>
          ) : null}
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <input
              ref={fileRef}
              type="file"
              accept=".eml,message/rfc822,text/plain"
              className="sr-only"
              id={`${fieldId}-file`}
              onChange={(event) => {
                void loadFile(event.target.files?.[0]);
                event.target.value = "";
              }}
            />
            <Button type="button" variant="outline" size="sm" onClick={() => fileRef.current?.click()}>
              <FileUp /> Load .eml file
            </Button>
          </div>
          <div className="flex gap-2">
            {raw ? (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => {
                  setRaw("");
                  setResult(null);
                  setError(null);
                }}
              >
                Clear
              </Button>
            ) : null}
            <Button type="submit" size="sm" disabled={ingest.isPending || !raw.trim()}>
              {ingest.isPending ? <Loader2 className="animate-spin" /> : <ScanSearch />}
              Classify and match
            </Button>
          </div>
        </div>
      </form>

      <AnimatePresence initial={false}>
        {result ? (
          <motion.div
            key={`${result.outcome}-${result.message?.id ?? "none"}`}
            initial={reduced ? false : { opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
            className="mt-4"
          >
            <IngestResult result={result} />
          </motion.div>
        ) : null}
      </AnimatePresence>
    </Surface>
  );
}

function IngestResult({ result }: { result: Schemas["EmailIngestResponse"] }) {
  const outcome = INGEST_OUTCOME[result.outcome] ?? { label: result.outcome, tone: "neutral" as const, detail: "" };
  const category = categoryLabel(result.category);
  const match = result.message ? MATCH_STATE[result.message.match_state] : null;
  return (
    <div aria-live="polite" className="space-y-3 rounded-lg border border-line bg-surface-2/50 p-4">
      <div className="flex flex-wrap items-center gap-1.5">
        <StatusBadge tone={outcome.tone}>{outcome.label}</StatusBadge>
        <StatusBadge tone={category.tone} dot={false}>
          {category.label}
        </StatusBadge>
        <span className="text-xs text-text-3 tabular">confidence {percent(result.confidence)}</span>
      </div>
      {outcome.detail ? <p className="text-xs text-text-2">{outcome.detail}</p> : null}

      {result.reasons.length ? (
        <div>
          <p className="mb-1 text-[11px] font-semibold tracking-wider text-text-3 uppercase">Why this category</p>
          <ul className="flex flex-wrap gap-1">
            {result.reasons.map((reason) => (
              <li key={reason} className="rounded-md bg-surface-3 px-1.5 py-0.5 text-[11px] text-text-2">
                {reason}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {result.message ? (
        <div className="text-xs text-text-2">
          <p className="font-medium text-text-1">{result.message.subject || "(no subject)"}</p>
          <p className="text-text-3">{result.message.sender}</p>
          {match ? (
            <p className="mt-1.5">
              Match: <StatusBadge tone={match.tone}>{match.label}</StatusBadge>
              {result.message.application_id ? (
                <span className="ml-1.5 text-text-3">application #{result.message.application_id}</span>
              ) : null}
            </p>
          ) : null}
        </div>
      ) : null}

      {result.suggestion ? (
        <p className="rounded-md border border-violet/25 bg-violet-soft px-3 py-2 text-xs text-text-1">
          Suggested: {fieldLabel(result.suggestion.field)} → <span className="font-medium">{result.suggestion.suggested_value}</span>{" "}
          for {result.suggestion.job_title || `application #${result.suggestion.application_id}`}. It is pending under
          Suggestions; nothing changes until you accept it.
        </p>
      ) : result.outcome === "created" && result.message?.match_state === "needs_review" ? (
        <p className="text-xs text-warning">Several applications could match. Pick the right one under “Needs your pick”.</p>
      ) : null}
    </div>
  );
}
