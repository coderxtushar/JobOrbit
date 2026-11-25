"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ChevronDown, Layers, Loader2, Sparkles } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import { toast } from "sonner";

import { EmptyState } from "@/components/shared/empty-state";
import { SectionHeading } from "@/components/shared/page-header";
import { ErrorState, errorMessage } from "@/components/shared/query-state";
import { StatusBadge } from "@/components/shared/status-badge";
import { Surface } from "@/components/shared/surface";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import type { Schemas } from "@/lib/api/client";
import { api } from "@/lib/api/endpoints";
import { formatDate, humanize } from "@/lib/formatting";
import { cn } from "@/lib/utils";

import { TagInput } from "./tag-input";

/** The job families the variant builder knows (app/services/resume_variants.py). */
const JOB_FAMILIES: Array<{ value: string; label: string }> = [
  { value: "backend", label: "Backend" },
  { value: "frontend", label: "Frontend" },
  { value: "fullstack", label: "Full-stack" },
  { value: "ai_ml", label: "AI / ML" },
  { value: "genai", label: "Generative AI" },
  { value: "cloud_devops", label: "Cloud / DevOps" },
  { value: "data", label: "Data" },
  { value: "general_software", label: "General software" },
];

const familyLabel = (value: string) => JOB_FAMILIES.find((item) => item.value === value)?.label ?? humanize(value);

function VariantCard({ variant }: { variant: Schemas["VariantRead"] }) {
  const [open, setOpen] = useState(false);
  const included = (variant.included_items ?? {}) as Record<string, unknown>;
  const omitted = Array.isArray(included.omitted_requested_skills) ? (included.omitted_requested_skills as string[]) : [];
  const projectNames = Array.isArray(included.project_names) ? (included.project_names as string[]) : [];
  const contentId = `variant-${variant.id}-content`;

  return (
    <div className="rounded-xl border border-line bg-surface-1 transition-colors hover:border-line-strong">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-controls={contentId}
        className="flex w-full items-start gap-3 rounded-xl p-3.5 text-left focus-visible:outline-2"
      >
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="truncate text-sm font-medium text-text-1">{variant.name}</p>
            <StatusBadge tone="cyan" dot={false}>
              {familyLabel(variant.job_family)}
            </StatusBadge>
            <span className="text-[11px] text-text-3 tabular">v{variant.version}</span>
          </div>
          <p className="text-xs text-text-3">
            Generated · {humanize(variant.generated_by) || "rule-based"} · {formatDate(variant.created_at)}
            {variant.emphasised_skills.length ? ` · emphasises ${variant.emphasised_skills.join(", ")}` : ""}
          </p>
          {omitted.length ? (
            <p className="flex items-start gap-1.5 text-xs text-warning">
              <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
              Not emphasised because your resume and profile do not list them: {omitted.join(", ")}
            </p>
          ) : null}
        </div>
        <ChevronDown className={cn("mt-1 size-4 shrink-0 text-text-3 transition-transform duration-200", open && "rotate-180")} />
      </button>
      <AnimatePresence initial={false}>
        {open ? (
          <motion.div
            id={contentId}
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
            className="overflow-hidden"
          >
            <div className="space-y-2 border-t border-line px-3.5 pt-3 pb-3.5">
              {projectNames.length ? (
                <p className="text-xs text-text-3">Projects included: {projectNames.join(", ")}</p>
              ) : null}
              <pre className="max-h-80 overflow-auto rounded-lg bg-surface-2 p-3 font-mono text-[11.5px] leading-relaxed whitespace-pre-wrap text-text-2">
                {variant.content}
              </pre>
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}

/**
 * Role-specific variants of one resume. The builder only reorders and selects facts already
 * in the resume and profile; a variant that would claim anything else is refused.
 */
export function ResumeVariants({ resume }: { resume: Schemas["ResumeRead"] }) {
  const queryClient = useQueryClient();
  const variants = useQuery({
    queryKey: ["resumes", resume.id, "variants"],
    queryFn: () => api.resumeVariants(resume.id),
  });
  const [family, setFamily] = useState("backend");
  const [skills, setSkills] = useState<string[]>([]);
  const [name, setName] = useState("");

  const create = useMutation({
    mutationFn: () =>
      api.createVariant({ resume_id: resume.id, job_family: family, emphasised_skills: skills, name: name.trim() }),
    onSuccess: (variant) => {
      toast.success(`Built “${variant.name}”`, { description: "Reordered from your own resume and profile; nothing added." });
      setSkills([]);
      setName("");
      queryClient.invalidateQueries({ queryKey: ["resumes", resume.id, "variants"] });
      queryClient.invalidateQueries({ queryKey: ["resumes"], exact: true });
    },
  });

  const items = variants.data?.items ?? [];

  return (
    <Surface className="p-5">
      <SectionHeading
        title="Variants"
        description="The same facts, ordered for a kind of role. Never adds a skill you have not listed."
        actions={<StatusBadge tone="violet" dot={false}>Generated</StatusBadge>}
      />
      <form
        className="space-y-3 rounded-xl border border-line bg-surface-2/40 p-4"
        onSubmit={(event) => {
          event.preventDefault();
          create.mutate();
        }}
      >
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="variant-family" className="text-xs text-text-2">
              Job family
            </Label>
            <Select value={family} onValueChange={setFamily}>
              <SelectTrigger id="variant-family" className="h-9 w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {JOB_FAMILIES.map((item) => (
                  <SelectItem key={item.value} value={item.value}>
                    {item.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="variant-name" className="text-xs text-text-2">
              Name <span className="text-text-3">(optional)</span>
            </Label>
            <Input
              id="variant-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder={`${familyLabel(family)} variant`}
              className="h-9"
            />
          </div>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="variant-skills" className="text-xs text-text-2">
            Skills to put first <span className="text-text-3">(optional)</span>
          </Label>
          <TagInput id="variant-skills" value={skills} onChange={setSkills} placeholder="e.g. python, fastapi" />
        </div>
        {create.isError ? (
          <p role="alert" className="flex items-start gap-2 text-xs text-danger">
            <AlertTriangle className="mt-0.5 size-3.5 shrink-0" /> {errorMessage(create.error)}
          </p>
        ) : null}
        <Button type="submit" size="sm" disabled={create.isPending}>
          {create.isPending ? <Loader2 className="animate-spin" /> : <Sparkles />} Build variant
        </Button>
      </form>

      <div className="mt-4 space-y-2">
        {variants.isLoading ? (
          <>
            <Skeleton className="h-16 w-full rounded-xl" />
            <Skeleton className="h-16 w-full rounded-xl" />
          </>
        ) : variants.isError ? (
          <ErrorState error={variants.error} onRetry={() => variants.refetch()} />
        ) : items.length === 0 ? (
          <EmptyState compact icon={Layers} title="No variants yet" description="Build one for the kind of role you apply to most." />
        ) : (
          items.map((variant) => <VariantCard key={variant.id} variant={variant} />)
        )}
      </div>
    </Surface>
  );
}
