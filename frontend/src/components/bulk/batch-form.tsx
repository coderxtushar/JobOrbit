"use client";

import { Info, ScanSearch } from "lucide-react";
import { Controller, type UseFormReturn } from "react-hook-form";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { SOURCES, SOURCE_LABEL } from "@/components/jobs/job-utils";
import { cn } from "@/lib/utils";

import type { BatchFormValues } from "./batch-utils";

const BANDS = [
  { value: "high", label: "Strong match", className: "data-[state=on]:border-success/40 data-[state=on]:bg-success-soft data-[state=on]:text-success" },
  { value: "review", label: "Worth a look", className: "data-[state=on]:border-violet/40 data-[state=on]:bg-violet-soft data-[state=on]:text-violet" },
  { value: "low", label: "Weak match", className: "data-[state=on]:border-line-strong data-[state=on]:bg-surface-3 data-[state=on]:text-text-1" },
] as const;

function FieldError({ message }: { message?: string }) {
  if (!message) return null;
  return (
    <p role="alert" className="text-[11.5px] text-danger">
      {message}
    </p>
  );
}

function Group({ title, description, children }: { title: string; description?: string; children: React.ReactNode }) {
  return (
    <fieldset className="space-y-3">
      <legend className="mb-3">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-text-3">{title}</span>
        {description ? <span className="mt-0.5 block text-[11.5px] text-text-3">{description}</span> : null}
      </legend>
      {children}
    </fieldset>
  );
}

function SwitchRow({
  id,
  label,
  description,
  checked,
  onCheckedChange,
}: {
  id: string;
  label: string;
  description: string;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
}) {
  return (
    <div className="flex items-start justify-between gap-3 rounded-lg border border-line bg-surface-2/40 p-2.5">
      <div className="space-y-0.5">
        <Label htmlFor={id} className="text-xs font-medium text-text-1">
          {label}
        </Label>
        <p className="text-[11px] leading-snug text-text-3">{description}</p>
      </div>
      <Switch id={id} checked={checked} onCheckedChange={onCheckedChange} />
    </div>
  );
}

/** Step 1: which jobs, and how to prepare them. Only fields BatchStartRequest accepts. */
export function BatchForm({
  form,
  onPreview,
  previewing,
}: {
  form: UseFormReturn<BatchFormValues>;
  onPreview: () => void;
  previewing: boolean;
}) {
  const {
    register,
    control,
    formState: { errors },
  } = form;

  return (
    <form
      className="space-y-6"
      onSubmit={(event) => {
        event.preventDefault();
        onPreview();
      }}
      noValidate
    >
      <Group title="Which jobs" description="Every field narrows the selection. Highest scores are taken first.">
        <div className="space-y-1.5">
          <Label className="text-xs font-medium text-text-2" id="bands-label">
            Match bands
          </Label>
          <Controller
            control={control}
            name="bands"
            render={({ field }) => (
              <ToggleGroup
                type="multiple"
                variant="outline"
                size="sm"
                value={field.value}
                onValueChange={(value) => field.onChange(value)}
                aria-labelledby="bands-label"
                className="flex-wrap"
              >
                {BANDS.map((band) => (
                  <ToggleGroupItem key={band.value} value={band.value} className={cn("px-3", band.className)}>
                    {band.label}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
            )}
          />
          <p className="text-[11px] text-text-3">None selected means every band.</p>
        </div>

        <div className="grid gap-3 sm:grid-cols-3">
          <div className="space-y-1.5">
            <Label htmlFor="min_score" className="text-xs font-medium text-text-2">
              Minimum score
            </Label>
            <Input
              id="min_score"
              inputMode="decimal"
              placeholder="Any"
              aria-invalid={Boolean(errors.min_score)}
              {...register("min_score")}
            />
            <FieldError message={errors.min_score?.message} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="max_age_days" className="text-xs font-medium text-text-2">
              Posted within (days)
            </Label>
            <Input
              id="max_age_days"
              inputMode="numeric"
              placeholder="Any"
              aria-invalid={Boolean(errors.max_age_days)}
              {...register("max_age_days")}
            />
            <FieldError message={errors.max_age_days?.message} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="limit" className="text-xs font-medium text-text-2">
              At most
            </Label>
            <Input
              id="limit"
              type="number"
              min={1}
              max={5000}
              aria-invalid={Boolean(errors.limit)}
              {...register("limit", { valueAsNumber: true })}
            />
            <FieldError message={errors.limit?.message} />
          </div>
        </div>
        <p className="-mt-1 text-[11px] text-text-3">
          Undated listings pass the age limit: the backend can&apos;t tell how old they are.
        </p>

        <div className="space-y-1.5">
          <Label htmlFor="titles" className="text-xs font-medium text-text-2">
            Titles containing
          </Label>
          <Textarea
            id="titles"
            rows={2}
            placeholder="e.g. AI Engineer, Backend Developer"
            aria-invalid={Boolean(errors.titles)}
            {...register("titles")}
          />
          <p className="text-[11px] text-text-3">Comma or line separated. A job matches if its title contains any of them.</p>
          <FieldError message={errors.titles?.message} />
        </div>

        <div className="space-y-1.5">
          <Label className="text-xs font-medium text-text-2" id="sources-label">
            Sources
          </Label>
          <Controller
            control={control}
            name="sources"
            render={({ field }) => (
              <ToggleGroup
                type="multiple"
                variant="outline"
                size="sm"
                spacing={1}
                value={field.value}
                onValueChange={(value) => field.onChange(value)}
                aria-labelledby="sources-label"
                className="flex-wrap"
              >
                {SOURCES.map((source) => (
                  <ToggleGroupItem
                    key={source}
                    value={source}
                    className="h-6 px-2 text-[11.5px] data-[state=on]:border-violet/40 data-[state=on]:bg-violet-soft data-[state=on]:text-violet"
                  >
                    {SOURCE_LABEL[source]}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
            )}
          />
          <p className="text-[11px] text-text-3">None selected means every source.</p>
        </div>

        <div className="grid gap-2 sm:grid-cols-2">
          <Controller
            control={control}
            name="include_unscored"
            render={({ field }) => (
              <SwitchRow
                id="include_unscored"
                label="Include unscored jobs"
                description="Jobs with no match score yet."
                checked={field.value}
                onCheckedChange={field.onChange}
              />
            )}
          />
          <Controller
            control={control}
            name="include_filtered"
            render={({ field }) => (
              <SwitchRow
                id="include_filtered"
                label="Include filtered-out jobs"
                description="Jobs your own filters held back."
                checked={field.value}
                onCheckedChange={field.onChange}
              />
            )}
          />
        </div>

        <div className="flex items-start gap-2 rounded-lg border border-dashed border-line-strong px-3 py-2 text-[11.5px] leading-relaxed text-text-3">
          <Info className="mt-0.5 size-3.5 shrink-0 text-cyan" aria-hidden />
          <p>
            Minimum confidence and excluded companies aren&apos;t offered here: the batch API
            (<code className="text-text-2">BatchSelectionIn</code>) doesn&apos;t accept them, so setting them would do
            nothing. Skip a company&apos;s jobs on the Jobs page to keep them out.
          </p>
        </div>
      </Group>

      <Group title="How to prepare">
        <Controller
          control={control}
          name="concurrency"
          render={({ field }) => (
            <div className="space-y-2">
              <div className="flex items-baseline justify-between">
                <Label htmlFor="concurrency" className="text-xs font-medium text-text-2">
                  Concurrency
                </Label>
                <span className="text-xs text-text-1 tabular">{field.value} at a time</span>
              </div>
              <Slider
                id="concurrency"
                aria-label="Concurrency"
                min={1}
                max={16}
                step={1}
                value={[field.value]}
                onValueChange={([value]) => field.onChange(value)}
              />
              <p className="text-[11px] text-text-3">On SQLite, values above about 4 buy little.</p>
            </div>
          )}
        />
        <div className="grid gap-3 sm:grid-cols-[10rem_1fr]">
          <div className="space-y-1.5">
            <Label htmlFor="max_attempts" className="text-xs font-medium text-text-2">
              Attempts per job
            </Label>
            <Input
              id="max_attempts"
              type="number"
              min={1}
              max={10}
              aria-invalid={Boolean(errors.max_attempts)}
              {...register("max_attempts", { valueAsNumber: true })}
            />
            <FieldError message={errors.max_attempts?.message} />
          </div>
          <div className="grid gap-2">
            <Controller
              control={control}
              name="include_cover_letter"
              render={({ field }) => (
                <SwitchRow
                  id="include_cover_letter"
                  label="Draft cover letters"
                  description="Write a cover letter for each job."
                  checked={field.value}
                  onCheckedChange={field.onChange}
                />
              )}
            />
            <Controller
              control={control}
              name="dry_run"
              render={({ field }) => (
                <SwitchRow
                  id="dry_run"
                  label="Dry run"
                  description="Go through every job but write nothing."
                  checked={field.value}
                  onCheckedChange={field.onChange}
                />
              )}
            />
          </div>
        </div>
      </Group>

      <Button type="submit" variant="outline" className="w-full" disabled={previewing}>
        <ScanSearch /> {previewing ? "Counting…" : "Preview selection"}
      </Button>
    </form>
  );
}
