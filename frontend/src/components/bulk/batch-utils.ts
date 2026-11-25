import { z } from "zod";

import type { Schemas } from "@/lib/api/client";
import type { Tone } from "@/lib/constants/states";

export type BatchRequest = Schemas["BatchStartRequest"];
export type BatchRun = Schemas["BatchRunRead"];
export type BatchDetail = Schemas["BatchRunDetail"];
export type BatchItem = Schemas["BatchItemRead"];
export type BatchItemStatus = Schemas["BatchItemStatus"];

export const ACTIVE_STATUSES = new Set<Schemas["BatchStatus"]>(["pending", "running", "cancelling"]);

export const ITEM_STATUS: Record<BatchItemStatus, { label: string; tone: Tone }> = {
  queued: { label: "Queued", tone: "neutral" },
  in_progress: { label: "Preparing", tone: "cyan" },
  prepared: { label: "Prepared", tone: "success" },
  needs_action: { label: "Needs action", tone: "warning" },
  skipped_duplicate: { label: "Skipped · duplicate", tone: "neutral" },
  skipped_ineligible: { label: "Skipped · ineligible", tone: "neutral" },
  failed: { label: "Failed", tone: "danger" },
  cancelled: { label: "Cancelled", tone: "neutral" },
};

export const ITEM_ORDER: BatchItemStatus[] = [
  "prepared",
  "needs_action",
  "skipped_duplicate",
  "skipped_ineligible",
  "failed",
  "in_progress",
  "queued",
  "cancelled",
];

const optionalNumber = (max: number, min: number, message: string, integer = false) =>
  z
    .string()
    .trim()
    .refine((value) => {
      if (value === "") return true;
      const parsed = Number(value);
      return Number.isFinite(parsed) && parsed >= min && parsed <= max && (!integer || Number.isInteger(parsed));
    }, message);

const whole = (min: number, max: number) =>
  z
    .number({ error: "Enter a number" })
    .int({ error: "Use a whole number" })
    .min(min, { error: `At least ${min}` })
    .max(max, { error: `At most ${max}` });

/** Mirrors BatchStartRequest / BatchSelectionIn bounds in app/schemas/batch.py. */
export const batchFormSchema = z.object({
  bands: z.array(z.enum(["high", "review", "low"])),
  min_score: optionalNumber(100, 0, "0–100, or leave empty"),
  max_age_days: optionalNumber(365, 1, "1–365 days, or leave empty", true),
  titles: z.string().max(2000, { error: "Too long" }),
  sources: z.array(z.string()),
  include_filtered: z.boolean(),
  include_unscored: z.boolean(),
  limit: whole(1, 5000),
  concurrency: whole(1, 16),
  max_attempts: whole(1, 10),
  include_cover_letter: z.boolean(),
  dry_run: z.boolean(),
});

export type BatchFormValues = z.infer<typeof batchFormSchema>;

export const BATCH_DEFAULTS: BatchFormValues = {
  bands: ["high"],
  min_score: "",
  max_age_days: "",
  titles: "",
  sources: [],
  include_filtered: false,
  include_unscored: false,
  limit: 25,
  concurrency: 4,
  max_attempts: 3,
  include_cover_letter: true,
  dry_run: false,
};

export function splitTitles(text: string): string[] {
  return [...new Set(text.split(/[\n,]/).map((title) => title.trim()).filter(Boolean))];
}

export function toBatchRequest(values: BatchFormValues): BatchRequest {
  return {
    selection: {
      bands: values.bands,
      min_score: values.min_score.trim() === "" ? null : Number(values.min_score),
      max_age_days: values.max_age_days.trim() === "" ? null : Number(values.max_age_days),
      titles: splitTitles(values.titles),
      sources: values.sources as Schemas["SourceName"][],
      include_filtered: values.include_filtered,
      include_unscored: values.include_unscored,
      limit: values.limit,
    },
    concurrency: values.concurrency,
    max_attempts: values.max_attempts,
    dry_run: values.dry_run,
    include_cover_letter: values.include_cover_letter,
    run_in_background: true,
  };
}

/** The part of a request that decides which jobs are covered (options don't change the preview). */
export function selectionKey(request: BatchRequest): string {
  return JSON.stringify(request.selection ?? {});
}

/** How many items reached a final state. */
export function finishedCount(detail: Pick<BatchDetail, "status_counts" | "total_items">): number {
  const counts = detail.status_counts ?? {};
  const open = (counts.queued ?? 0) + (counts.in_progress ?? 0);
  return Math.max(0, detail.total_items - open);
}
