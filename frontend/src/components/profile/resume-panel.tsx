"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  FileText,
  FileUp,
  Loader2,
  Star,
  UploadCloud,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { EmptyState } from "@/components/shared/empty-state";
import { SectionHeading } from "@/components/shared/page-header";
import { ErrorState, errorMessage } from "@/components/shared/query-state";
import { StatusBadge } from "@/components/shared/status-badge";
import { Surface } from "@/components/shared/surface";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import type { Schemas } from "@/lib/api/client";
import { api } from "@/lib/api/endpoints";
import { formatDate, formatNumber } from "@/lib/formatting";
import { cn } from "@/lib/utils";

import { ParsedProposal, type ProposalSelection } from "./parsed-proposal";
import { ResumeVariants } from "./resume-variants";

const ACCEPTED = [".pdf", ".docx"];

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function UploadZone({ hasResumes, onUploaded }: { hasResumes: boolean; onUploaded: (result: Schemas["ResumeUploadResponse"]) => void }) {
  const queryClient = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [label, setLabel] = useState("base");
  const [primary, setPrimary] = useState(!hasResumes);
  const [localError, setLocalError] = useState<string | null>(null);

  const upload = useMutation({
    mutationFn: (chosen: File) => api.uploadResume(chosen, label.trim() || "base", primary),
    onSuccess: (result) => {
      toast.success("Resume stored and parsed", {
        description: "Nothing was written to your profile. Review the proposal below.",
      });
      setFile(null);
      queryClient.invalidateQueries({ queryKey: ["resumes"] });
      onUploaded(result);
    },
  });

  const choose = (candidate: File | undefined | null) => {
    upload.reset();
    if (!candidate) return;
    const lower = candidate.name.toLowerCase();
    if (!ACCEPTED.some((ext) => lower.endsWith(ext))) {
      setLocalError("Only PDF and DOCX resumes can be read.");
      setFile(null);
      return;
    }
    setLocalError(null);
    setFile(candidate);
  };

  return (
    <Surface className="p-5">
      <SectionHeading title="Upload a resume" description="PDF or DOCX. The file stays on this machine; its fields are extracted locally." />
      <div
        role="button"
        tabIndex={0}
        aria-label="Choose a resume file, or drop one here"
        onClick={() => inputRef.current?.click()}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          choose(event.dataTransfer.files?.[0]);
        }}
        className={cn(
          "group relative flex flex-col items-center justify-center gap-2 overflow-hidden rounded-xl border border-dashed border-line-strong px-6 py-8 text-center transition-[border-color,background-color,box-shadow] duration-200",
          "hover:border-violet/50 hover:bg-violet-soft/40 focus-visible:outline-2",
          dragging && "border-violet bg-violet-soft shadow-glow",
        )}
      >
        <motion.div
          animate={{ y: dragging ? -3 : 0, scale: dragging ? 1.06 : 1 }}
          transition={{ type: "spring", stiffness: 320, damping: 22 }}
          className="grid size-11 place-items-center rounded-xl bg-violet-soft text-violet ring-1 ring-inset ring-violet/20"
        >
          <UploadCloud className="size-5" />
        </motion.div>
        <p className="text-sm font-medium text-text-1">{dragging ? "Drop to choose this file" : "Drop a resume here, or click to browse"}</p>
        <p className="text-xs text-text-3">.pdf or .docx</p>
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          className="sr-only"
          tabIndex={-1}
          onChange={(event) => {
            choose(event.target.files?.[0]);
            event.target.value = "";
          }}
        />
      </div>

      {localError ? (
        <p role="alert" className="mt-3 text-xs text-danger">
          {localError}
        </p>
      ) : null}

      <AnimatePresence initial={false}>
        {file ? (
          <motion.div
            key="chosen"
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
            className="overflow-hidden"
          >
            <div className="mt-4 space-y-4 rounded-xl border border-line bg-surface-2/40 p-4">
              <div className="flex items-center gap-3">
                <FileText className="size-4 shrink-0 text-violet" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-text-1">{file.name}</p>
                  <p className="text-xs text-text-3 tabular">{formatBytes(file.size)}</p>
                </div>
                <Button type="button" variant="ghost" size="sm" onClick={() => setFile(null)} disabled={upload.isPending}>
                  Change
                </Button>
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor="resume-label" className="text-xs text-text-2">
                    Label
                  </Label>
                  <Input id="resume-label" value={label} onChange={(event) => setLabel(event.target.value)} maxLength={200} className="h-9" />
                </div>
                <label className="flex items-center justify-between gap-3 rounded-lg border border-line px-3 py-2 sm:mt-6">
                  <span className="text-xs text-text-2">Make it the primary resume</span>
                  <Switch checked={primary} onCheckedChange={setPrimary} aria-label="Make it the primary resume" />
                </label>
              </div>
              {upload.isError ? (
                <p role="alert" className="flex items-start gap-2 text-xs text-danger">
                  <AlertTriangle className="mt-0.5 size-3.5 shrink-0" /> {errorMessage(upload.error)}
                </p>
              ) : null}
              <Button type="button" onClick={() => upload.mutate(file)} disabled={upload.isPending} className="w-full sm:w-auto">
                {upload.isPending ? <Loader2 className="animate-spin" /> : <FileUp />}
                {upload.isPending ? "Uploading and parsing…" : "Upload and parse"}
              </Button>
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </Surface>
  );
}

function ResumeRow({
  resume,
  selected,
  onSelect,
}: {
  resume: Schemas["ResumeRead"];
  selected: boolean;
  onSelect: () => void;
}) {
  const queryClient = useQueryClient();
  const makePrimary = useMutation({
    mutationFn: () => api.setPrimaryResume(resume.id),
    onSuccess: () => {
      toast.success(`“${resume.original_filename}” is now the primary resume`);
      queryClient.invalidateQueries({ queryKey: ["resumes"] });
    },
    onError: (error) => toast.error("Could not change the primary resume", { description: errorMessage(error) }),
  });

  return (
    <div
      className={cn(
        "group relative rounded-xl border p-3.5 transition-[border-color,background-color,box-shadow] duration-200",
        selected ? "border-violet/40 bg-violet-soft/50 shadow-glow" : "border-line bg-surface-1 hover:border-line-strong",
      )}
    >
      <button
        type="button"
        onClick={onSelect}
        aria-pressed={selected}
        className="absolute inset-0 rounded-xl focus-visible:outline-2"
        aria-label={`Show parsed fields and variants for ${resume.original_filename}`}
      />
      <div className="pointer-events-none relative flex items-start gap-3">
        <div className="grid size-9 shrink-0 place-items-center rounded-lg bg-surface-3 text-text-2 ring-1 ring-inset ring-line-strong">
          <FileText className="size-4" />
        </div>
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="truncate text-sm font-medium text-text-1">{resume.original_filename}</p>
            {resume.is_primary ? (
              <StatusBadge tone="violet">Primary</StatusBadge>
            ) : null}
          </div>
          <p className="text-xs text-text-3 tabular">
            {resume.label || "—"} · {formatBytes(resume.file_size_bytes)} · {formatNumber(resume.text_character_count)} chars read ·
            uploaded {formatDate(resume.created_at)}
          </p>
          <p className="text-xs text-text-3 tabular">
            {resume.variant_count} variant{resume.variant_count === 1 ? "" : "s"}
            {resume.parse_warnings.length ? (
              <span className="text-warning">
                {" "}
                · {resume.parse_warnings.length} parse warning{resume.parse_warnings.length === 1 ? "" : "s"}
              </span>
            ) : null}
          </p>
        </div>
        {!resume.is_primary ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="pointer-events-auto relative"
            onClick={() => makePrimary.mutate()}
            disabled={makePrimary.isPending}
          >
            {makePrimary.isPending ? <Loader2 className="animate-spin" /> : <Star />} Make primary
          </Button>
        ) : null}
      </div>
    </div>
  );
}

export function ResumePanel({ onApplyProposal }: { onApplyProposal: (selection: ProposalSelection) => void }) {
  const resumes = useQuery({ queryKey: ["resumes"], queryFn: api.resumes });
  const [chosenId, setChosenId] = useState<number | null>(null);
  const [justUploaded, setJustUploaded] = useState<number | null>(null);

  const items = resumes.data?.items ?? [];
  const selected =
    items.find((item) => item.id === chosenId) ?? items.find((item) => item.is_primary) ?? items[0] ?? null;

  const parsed = useQuery({
    queryKey: ["resumes", selected?.id, "parsed"],
    queryFn: () => api.parsedResume(selected!.id),
    enabled: Boolean(selected),
  });

  return (
    <div className="space-y-6">
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
        <UploadZone
          key={items.length > 0 ? "has" : "none"}
          hasResumes={items.length > 0}
          onUploaded={(result) => {
            setChosenId(result.resume.id);
            setJustUploaded(result.resume.id);
          }}
        />
        <Surface className="p-5">
          <SectionHeading
            title="Stored resumes"
            description="The primary resume is attached to new applications and used for variants by default."
          />
          {resumes.isLoading ? (
            <div className="space-y-2">
              <Skeleton className="h-[76px] w-full rounded-xl" />
              <Skeleton className="h-[76px] w-full rounded-xl" />
            </div>
          ) : resumes.isError ? (
            <ErrorState error={resumes.error} onRetry={() => resumes.refetch()} />
          ) : items.length === 0 ? (
            <EmptyState compact icon={FileText} title="No resume yet" description="Upload one to extract its fields and build role-specific variants." />
          ) : (
            <div className="space-y-2">
              {items.map((resume) => (
                <ResumeRow
                  key={resume.id}
                  resume={resume}
                  selected={selected?.id === resume.id}
                  onSelect={() => setChosenId(resume.id)}
                />
              ))}
            </div>
          )}
        </Surface>
      </div>

      {selected ? (
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
          <Surface className="p-5">
            <SectionHeading
              title="Extracted fields"
              description={
                <>
                  From <span className="text-text-2">{selected.original_filename}</span>. A proposal only — nothing here is in
                  your profile until you copy it and save.
                </>
              }
              actions={
                justUploaded === selected.id ? (
                  <StatusBadge tone="cyan">
                    <CheckCircle2 className="size-3" /> Just parsed
                  </StatusBadge>
                ) : null
              }
            />
            {selected.parse_warnings.length ? (
              <ul className="mb-4 space-y-1 rounded-lg border border-warning/25 bg-warning-soft px-3 py-2 text-xs text-text-2">
                {selected.parse_warnings.map((warning) => (
                  <li key={warning} className="flex gap-2">
                    <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warning" /> {warning}
                  </li>
                ))}
              </ul>
            ) : null}
            {parsed.isLoading ? (
              <div className="space-y-2">
                {Array.from({ length: 6 }).map((_, index) => (
                  <Skeleton key={index} className="h-10 w-full" />
                ))}
              </div>
            ) : parsed.isError ? (
              <ErrorState error={parsed.error} onRetry={() => parsed.refetch()} />
            ) : parsed.data ? (
              <ParsedProposal key={selected.id} parsed={parsed.data} onApply={onApplyProposal} />
            ) : null}
          </Surface>
          <ResumeVariants resume={selected} />
        </div>
      ) : null}
    </div>
  );
}
