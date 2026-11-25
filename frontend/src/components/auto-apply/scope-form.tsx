"use client";

import { AnimatePresence, motion } from "motion/react";
import { FlaskConical, Loader2, Radar, Send, ShieldAlert, SlidersHorizontal, X } from "lucide-react";
import Link from "next/link";
import { Controller, type UseFormReturn } from "react-hook-form";

import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";

import { ChipInput, ChipToggleGroup, Field, HardConstraintTag, Segmented } from "./form-bits";
import {
  AGE_WINDOWS,
  BANDS,
  CONFIDENCE,
  REMOTE_CHOICES,
  ROLE_FAMILIES,
  windowLabel,
  type ScopeValues,
} from "./scope";

/**
 * The run's scope. Score, band, freshness and confidence are thresholds; everything in the
 * "Hard constraints" block removes a job on its own, whatever it scores.
 */
export function ScopeForm({
  form,
  platformOptions,
  onBuild,
  building,
  urlJobIds,
  planState,
}: {
  form: UseFormReturn<ScopeValues>;
  platformOptions: { value: string; label: string }[];
  onBuild: () => void;
  building: boolean;
  urlJobIds: number[];
  planState: "none" | "current" | "stale";
}) {
  const { control, formState } = form;
  const errors = formState.errors;

  return (
    <form
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        onBuild();
      }}
      className="orbit-card overflow-hidden"
      aria-label="Run scope"
    >
      <div className="flex items-center gap-3 border-b border-line px-5 py-3.5">
        <StepDot n={1} />
        <div className="min-w-0 flex-1">
          <h2 className="font-heading text-[15px] font-semibold text-text-1">Scope</h2>
          <p className="text-xs text-text-3">What a run may touch. Starts from the scope you last authorised.</p>
        </div>
        <SlidersHorizontal className="size-4 text-text-3" />
      </div>

      {urlJobIds.length ? (
        <div className="flex items-center gap-3 border-b border-line bg-cyan-soft px-5 py-2.5 text-xs text-text-1">
          <Radar className="size-4 shrink-0 text-cyan" />
          <p className="min-w-0 flex-1">
            Limited to the <strong className="tabular">{urlJobIds.length}</strong> job(s) you picked in Job discovery. The
            preflight checks each one against the scope below.
          </p>
          <Link href="/auto-apply" className="inline-flex items-center gap-1 text-text-2 hover:text-text-1">
            <X className="size-3.5" /> Use whole scope
          </Link>
        </div>
      ) : null}

      <div className="space-y-6 p-5">
        {/* Thresholds */}
        <fieldset className="grid gap-5 sm:grid-cols-2 xl:grid-cols-4">
          <legend className="sr-only">Thresholds</legend>
          <Controller
            control={control}
            name="bands"
            render={({ field }) => (
              <Field label="Match band" error={errors.bands?.message}>
                <ChipToggleGroup
                  label="Match band"
                  options={BANDS.map((band) => ({ value: band.value, label: band.label }))}
                  value={field.value}
                  onChange={(next) => field.onChange(next)}
                />
              </Field>
            )}
          />
          <Controller
            control={control}
            name="min_score"
            render={({ field }) => (
              <Field
                label="Minimum score"
                aside={<span className="tabular font-heading text-sm font-semibold text-violet">{field.value}</span>}
              >
                <Slider
                  aria-label="Minimum score"
                  className="mt-2.5"
                  min={0}
                  max={100}
                  step={1}
                  value={[field.value]}
                  onValueChange={([next]) => field.onChange(next)}
                />
                <div className="mt-1 flex justify-between text-[10.5px] text-text-3 tabular">
                  <span>0</span>
                  <span>100</span>
                </div>
              </Field>
            )}
          />
          <Controller
            control={control}
            name="max_age_hours"
            render={({ field }) => (
              <Field label="Posted within" htmlFor="scope-window">
                <Select value={String(field.value)} onValueChange={(next) => field.onChange(Number(next))}>
                  <SelectTrigger id="scope-window" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {AGE_WINDOWS.map((hours) => (
                      <SelectItem key={hours} value={String(hours)}>
                        {windowLabel(hours)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
            )}
          />
          <Controller
            control={control}
            name="min_confidence"
            render={({ field }) => (
              <Field label="Minimum confidence" hint="How much of the posting the score could check.">
                <Segmented
                  label="Minimum confidence"
                  options={CONFIDENCE.map((value) => ({ value, label: value }))}
                  value={field.value}
                  onChange={field.onChange}
                />
              </Field>
            )}
          />
        </fieldset>

        {/* Hard constraints */}
        <fieldset className="relative rounded-xl border border-warning/25 bg-warning-soft/40 p-4 pt-3">
          <legend className="flex items-center gap-2 px-1 text-xs font-semibold text-text-1">
            <ShieldAlert className="size-3.5 text-warning" /> Hard constraints
          </legend>
          <p className="mb-4 text-xs text-text-2">
            Each one removes a job on its own, with a reason, however well it scores.
          </p>
          <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-4">
            <Controller
              control={control}
              name="role_families"
              render={({ field }) => (
                <Field label="Role families" hint="None selected allows every family." className="sm:col-span-2" aside={<HardConstraintTag />}>
                  <ChipToggleGroup label="Role families" options={ROLE_FAMILIES} value={field.value} onChange={field.onChange} />
                </Field>
              )}
            />
            <Controller
              control={control}
              name="locations"
              render={({ field }) => (
                <Field label="Allowed locations" hint="Empty uses your profile's locations." aside={<HardConstraintTag />}>
                  <ChipInput
                    ariaLabel="Allowed locations"
                    value={field.value}
                    onChange={field.onChange}
                    placeholder="Bengaluru, Remote…"
                  />
                </Field>
              )}
            />
            <Controller
              control={control}
              name="remote_preference"
              render={({ field }) => (
                <Field label="Remote preference" htmlFor="scope-remote" aside={<HardConstraintTag />}>
                  <Select value={field.value} onValueChange={field.onChange}>
                    <SelectTrigger id="scope-remote" className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {Object.entries(REMOTE_CHOICES).map(([value, label]) => (
                        <SelectItem key={value} value={value}>
                          {label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>
              )}
            />
            <Controller
              control={control}
              name="experience_tolerance_years"
              render={({ field }) => (
                <Field
                  label="Experience tolerance"
                  htmlFor="scope-tolerance"
                  hint="Years above your experience a listing may ask for. Empty means none."
                  error={errors.experience_tolerance_years?.message}
                  aside={<HardConstraintTag />}
                >
                  <NumberInput id="scope-tolerance" step={0.5} min={0} max={20} suffix="yrs" value={field.value} onChange={field.onChange} />
                </Field>
              )}
            />
            <Controller
              control={control}
              name="platforms"
              render={({ field }) => (
                <Field label="Platforms" hint="None selected allows every platform." aside={<HardConstraintTag />}>
                  {platformOptions.length ? (
                    <ChipToggleGroup label="Platforms" options={platformOptions} value={field.value} onChange={field.onChange} />
                  ) : (
                    <p className="text-xs text-text-3">Platform list unavailable.</p>
                  )}
                </Field>
              )}
            />
            <Controller
              control={control}
              name="excluded_companies"
              render={({ field }) => (
                <Field label="Excluded employers" hint="Never applied to in this run." aside={<HardConstraintTag />}>
                  <ChipInput ariaLabel="Excluded employers" value={field.value} onChange={field.onChange} placeholder="Type and press Enter" />
                </Field>
              )}
            />
            <Controller
              control={control}
              name="max_submissions"
              render={({ field }) => (
                <Field
                  label="Max submissions"
                  htmlFor="scope-max"
                  hint="Attempts this run may make, 1–500."
                  error={errors.max_submissions?.message}
                  aside={<HardConstraintTag />}
                >
                  <NumberInput id="scope-max" step={1} min={1} max={500} value={field.value} onChange={(next) => field.onChange(next ?? Number.NaN)} />
                </Field>
              )}
            />
            <Controller
              control={control}
              name="daily_cap"
              render={({ field }) => (
                <Field
                  label="Daily cap"
                  htmlFor="scope-cap"
                  hint="Empty uses the installation's cap. The lower one wins."
                  error={errors.daily_cap?.message}
                  aside={<HardConstraintTag />}
                >
                  <NumberInput id="scope-cap" step={1} min={1} max={500} suffix="/ day" value={field.value} onChange={field.onChange} />
                </Field>
              )}
            />
          </div>
        </fieldset>

        {/* Run mode */}
        <div className="grid gap-3 md:grid-cols-2">
          <Controller
            control={control}
            name="include_cover_letter"
            render={({ field }) => (
              <label
                htmlFor="scope-cover"
                className="flex cursor-pointer items-start gap-3 rounded-xl border border-line bg-surface-2/40 p-3.5 transition-colors hover:border-line-strong"
              >
                <Switch id="scope-cover" checked={field.value} onCheckedChange={field.onChange} className="mt-0.5" />
                <span>
                  <span className="block text-sm font-medium text-text-1">Include a cover letter</span>
                  <span className="block text-xs text-text-3">Drafted per job at preparation; shown in the preflight.</span>
                </span>
              </label>
            )}
          />
          <Controller
            control={control}
            name="dry_run"
            render={({ field }) => (
              <label
                htmlFor="scope-dry"
                className={cn(
                  "flex cursor-pointer items-start gap-3 rounded-xl border p-3.5 transition-[background-color,border-color,box-shadow] duration-200",
                  field.value
                    ? "border-violet/30 bg-violet-soft hover:border-violet/50"
                    : "border-danger/40 bg-danger-soft shadow-[0_0_0_1px_var(--danger-soft)]",
                )}
              >
                <Switch id="scope-dry" checked={field.value} onCheckedChange={field.onChange} className="mt-0.5" />
                <span className="min-w-0">
                  <span className="flex items-center gap-1.5 text-sm font-medium text-text-1">
                    {field.value ? <FlaskConical className="size-3.5 text-violet" /> : <Send className="size-3.5 text-danger" />}
                    {field.value ? "Dry run — send nothing" : "Live run — real applications"}
                  </span>
                  <span className="block text-xs text-text-2">
                    {field.value
                      ? "Forms are filled and screenshotted; nothing is submitted. Leave this on until the preflight looks right."
                      : "Ticked jobs on permitted platforms will be submitted to employers. Needs a current preflight."}
                  </span>
                </span>
              </label>
            )}
          />
        </div>
      </div>

      <div className="flex flex-col gap-3 border-t border-line bg-surface-2/40 px-5 py-3 sm:flex-row sm:items-center">
        <AnimatePresence mode="wait" initial={false}>
          <motion.p
            key={planState}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.16 }}
            className={cn(
              "min-w-0 flex-1 text-xs",
              planState === "current" && "text-success",
              planState === "stale" && "text-warning",
              planState === "none" && "text-text-3",
            )}
          >
            {planState === "current"
              ? "The preflight below matches this scope."
              : planState === "stale"
                ? "The scope changed since the preflight was built. Build it again before a live run."
                : "Nothing is sent by building a preflight: it only reads your data."}
          </motion.p>
        </AnimatePresence>
        <Button type="submit" disabled={building} className="shadow-glow">
          {building ? <Loader2 className="animate-spin" /> : <Radar />}
          {building ? "Building preflight…" : planState === "none" ? "Build preflight" : "Rebuild preflight"}
        </Button>
      </div>
    </form>
  );
}

export function StepDot({ n }: { n: number }) {
  return (
    <span className="grid size-7 shrink-0 place-items-center rounded-full bg-violet-soft font-heading text-xs font-semibold text-violet ring-1 ring-inset ring-violet/25">
      {n}
    </span>
  );
}

function NumberInput({
  id,
  value,
  onChange,
  step,
  min,
  max,
  suffix,
}: {
  id: string;
  value: number | null;
  onChange: (next: number | null) => void;
  step: number;
  min: number;
  max: number;
  suffix?: string;
}) {
  return (
    <div className="relative">
      <Input
        id={id}
        type="number"
        inputMode="decimal"
        step={step}
        min={min}
        max={max}
        value={value === null || Number.isNaN(value) ? "" : value}
        onChange={(event) => onChange(event.target.value === "" ? null : Number(event.target.value))}
        className={cn("tabular", suffix && "pr-12")}
      />
      {suffix ? (
        <span className="pointer-events-none absolute inset-y-0 right-2.5 flex items-center text-xs text-text-3">{suffix}</span>
      ) : null}
    </div>
  );
}
