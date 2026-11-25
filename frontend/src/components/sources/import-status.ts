import type { Tone } from "@/lib/constants/states";

/** Import-run status from the backend's ImportStatus enum. */
export const IMPORT_STATUS: Record<string, { label: string; tone: Tone }> = {
  running: { label: "Running", tone: "cyan" },
  success: { label: "Success", tone: "success" },
  partial: { label: "Partial", tone: "warning" },
  failed: { label: "Failed", tone: "danger" },
  skipped_unsupported: { label: "Skipped", tone: "neutral" },
};

/** One import or discovery run, as returned by POST /api/jobs/discover and /import-csv. */
export interface ImportRunRow {
  id: number;
  source: string;
  trigger: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  records_received: number;
  records_invalid: number;
  jobs_created: number;
  jobs_updated: number;
  duplicates_detected: number;
  message: string;
  errors: string[];
}

/** /api/import-runs rows are loose dicts; read each field defensively. */
export function toImportRunRow(record: Record<string, unknown>): ImportRunRow {
  const num = (value: unknown) => (typeof value === "number" ? value : 0);
  const str = (value: unknown) => (typeof value === "string" ? value : "");
  return {
    id: num(record.id),
    source: str(record.source),
    trigger: str(record.trigger),
    status: str(record.status),
    started_at: str(record.started_at),
    finished_at: typeof record.finished_at === "string" ? record.finished_at : null,
    records_received: num(record.records_received),
    records_invalid: num(record.records_invalid),
    jobs_created: num(record.jobs_created),
    jobs_updated: num(record.jobs_updated),
    duplicates_detected: num(record.duplicates_detected),
    message: str(record.message),
    errors: Array.isArray(record.errors) ? record.errors.map(String) : [],
  };
}
