"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Download, FileUp, Loader2, Upload, X } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { errorMessage } from "@/components/shared/query-state";
import { SectionHeading } from "@/components/shared/page-header";
import { Surface } from "@/components/shared/surface";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { Schemas } from "@/lib/api/client";
import { api } from "@/lib/api/endpoints";
import { cn } from "@/lib/utils";

import { ImportSummaryCard } from "./import-summary";

/** The same template the Streamlit discovery page offered. */
const CSV_TEMPLATE =
  "Job Title,Company Name,Location,Link,Job ID,Source,Key Skills,Experience,Salary,Posted,Job Description\n" +
  'Backend Developer,Acme Technologies,"Bengaluru, India",https://example.com/jobs/1,ACME-1,' +
  "linkedin,Python|FastAPI|PostgreSQL,0-2 years,6-10 LPA,2 days ago," +
  '"Build REST APIs with Python and FastAPI."\n';

const COLUMNS: { field: string; names: string; required?: boolean }[] = [
  { field: "Title", names: "title, job title, position, role, designation", required: true },
  { field: "Company", names: "company, company name, employer, organization", required: true },
  { field: "URL or ID", names: "url, link, apply url · id, job id, reference", required: true },
  { field: "Location", names: "location, city, place" },
  { field: "Posted", names: "posted, date posted, published, \"3 days ago\"" },
  { field: "Description", names: "description, job description, jd, details" },
  { field: "Salary / experience", names: "salary, ctc, package · experience, exp" },
  { field: "Source", names: "source (overrides the choice below per row)" },
];

const MAX_BYTES = 8 * 1024 * 1024;
const ACCEPT = ".csv,.tsv,.json,text/csv,application/json,text/tab-separated-values";

function downloadTemplate() {
  const blob = new Blob([CSV_TEMPLATE], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "job_import_template.csv";
  link.click();
  URL.revokeObjectURL(url);
}

export function ImportPanel({ sources }: { sources: Schemas["SourceRead"][] }) {
  const queryClient = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [source, setSource] = useState<Schemas["SourceName"]>("csv");
  const importable = sources.filter((item) => item.effective_capabilities.manual_import_enabled);

  const upload = useMutation({
    mutationFn: ({ file, source }: { file: File; source: Schemas["SourceName"] }) => api.importJobsCsv(file, source),
    onSuccess: (summary) => {
      toast.success(`Imported ${file?.name ?? "file"}`, {
        description: `${summary.jobs_created} new, ${summary.jobs_updated} enriched, ${summary.duplicates_detected} duplicate, ${summary.records_invalid} invalid.`,
      });
      setFile(null);
      void queryClient.invalidateQueries({ queryKey: ["sources"] });
      void queryClient.invalidateQueries({ queryKey: ["analytics"] });
    },
    onError: (error) => toast.error("The file was not imported", { description: errorMessage(error) }),
  });

  const choose = (candidate: File | undefined) => {
    if (!candidate) return;
    if (candidate.size > MAX_BYTES) {
      toast.error("That file is too large", { description: "The import limit is 8 MB." });
      return;
    }
    upload.reset();
    setFile(candidate);
  };

  return (
    <Surface className="p-5">
      <SectionHeading
        title="Import a file"
        description="The path that always works: no credentials, no network access. CSV, TSV or JSON, up to 8 MB and 2,000 rows."
        actions={
          <Button variant="ghost" size="sm" onClick={downloadTemplate}>
            <Download /> CSV template
          </Button>
        }
      />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <div className="space-y-3">
          <div
            onDragOver={(event) => {
              event.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(event) => {
              event.preventDefault();
              setDragging(false);
              choose(event.dataTransfer.files[0]);
            }}
            className={cn(
              "flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed px-4 py-7 text-center transition-colors",
              dragging ? "border-violet bg-violet-soft" : "border-line-strong bg-surface-2/30",
            )}
          >
            <span className="grid size-10 place-items-center rounded-xl bg-violet-soft text-violet ring-1 ring-inset ring-violet/20">
              <FileUp className="size-5" />
            </span>
            {file ? (
              <div className="flex items-center gap-2 text-sm text-text-1">
                <span className="max-w-64 truncate font-medium">{file.name}</span>
                <span className="text-xs text-text-3">{(file.size / 1024).toFixed(1)} KB</span>
                <Button variant="ghost" size="icon-xs" aria-label="Remove file" onClick={() => setFile(null)}>
                  <X />
                </Button>
              </div>
            ) : (
              <p className="text-sm text-text-2">Drop an export here, or</p>
            )}
            <input
              ref={inputRef}
              type="file"
              accept={ACCEPT}
              className="sr-only"
              aria-label="Choose a CSV, TSV or JSON file"
              onChange={(event) => {
                choose(event.target.files?.[0]);
                event.target.value = "";
              }}
            />
            <Button variant="outline" size="sm" onClick={() => inputRef.current?.click()}>
              {file ? "Choose another file" : "Choose a file"}
            </Button>
          </div>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <div className="flex-1 space-y-1.5">
              <Label htmlFor="import-source" className="text-xs text-text-2">
                Attribute these jobs to
              </Label>
              <Select value={source} onValueChange={(value) => setSource(value as Schemas["SourceName"])}>
                <SelectTrigger id="import-source" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(importable.length ? importable : [{ source: "csv", display_name: "CSV import" }]).map((item) => (
                    <SelectItem key={item.source} value={item.source}>
                      {item.display_name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <Button
              onClick={() => file && upload.mutate({ file, source })}
              disabled={!file || upload.isPending}
              className="sm:w-36"
            >
              {upload.isPending ? <Loader2 className="animate-spin" /> : <Upload />}
              {upload.isPending ? "Importing…" : "Import file"}
            </Button>
          </div>
          <p className="text-[11.5px] text-text-3">
            Used for de-duplication and tracking. A &ldquo;Source&rdquo; column in the file overrides it per row.
          </p>
          {upload.data ? (
            <ImportSummaryCard
              summary={upload.data}
              displayName={sources.find((item) => item.source === upload.data.source)?.display_name}
            />
          ) : null}
        </div>

        <Collapsible defaultOpen className="rounded-xl border border-line bg-surface-2/30 p-4">
          <CollapsibleTrigger className="text-left text-xs font-semibold uppercase tracking-wider text-text-3 hover:text-text-1">
            Recognised columns
          </CollapsibleTrigger>
          <CollapsibleContent>
            <p className="mt-2 text-xs leading-relaxed text-text-3">
              Column names are matched case-insensitively against these synonyms, so exports from different boards
              import without editing. Invalid rows are counted and reported with their row number.
            </p>
            <dl className="mt-3 space-y-2">
              {COLUMNS.map((column) => (
                <div key={column.field} className="grid grid-cols-[7.5rem_1fr] gap-2 text-xs">
                  <dt className="font-medium text-text-1">
                    {column.field}
                    {column.required ? <span className="ml-0.5 text-violet">*</span> : null}
                  </dt>
                  <dd className="text-text-3">{column.names}</dd>
                </div>
              ))}
            </dl>
            <p className="mt-3 text-[11px] text-text-3">
              <span className="text-violet">*</span> A row needs a title, a company, and a URL or ID. JSON files hold a
              list of job objects with the same field names.
            </p>
          </CollapsibleContent>
        </Collapsible>
      </div>
    </Surface>
  );
}
