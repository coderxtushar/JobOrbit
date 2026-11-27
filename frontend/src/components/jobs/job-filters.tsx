"use client";

import { RotateCcw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { JOB_STATUS } from "@/lib/constants/states";

import {
  AGE_OPTIONS,
  JOB_STATUSES,
  SOURCES,
  SOURCE_LABEL,
  activeFilterCount,
  type JobFilters,
  type JobStatus,
  type SourceName,
} from "./job-utils";

const ANY = "__any";

function Field({ label, htmlFor, children, hint }: { label: string; htmlFor?: string; children: React.ReactNode; hint?: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between gap-2">
        <Label htmlFor={htmlFor} className="text-xs font-medium text-text-2">
          {label}
        </Label>
        {hint}
      </div>
      {children}
    </div>
  );
}

/**
 * Exactly the filters GET /api/jobs supports, nothing more. Changes are written to the
 * URL by the caller; free-text fields arrive already debounced.
 */
export function JobFilterPanel({
  idPrefix,
  filters,
  onChange,
  onReset,
  companyText,
  onCompanyTextChange,
  minScoreDraft,
  onMinScoreDraftChange,
  fixedStatus,
}: {
  idPrefix: string;
  filters: JobFilters;
  onChange: (patch: Partial<JobFilters>) => void;
  onReset: () => void;
  companyText: string;
  onCompanyTextChange: (value: string) => void;
  minScoreDraft: number | null;
  onMinScoreDraftChange: (value: number | null) => void;
  fixedStatus?: JobStatus;
}) {
  const active = activeFilterCount(filters, fixedStatus);
  const id = (name: string) => `${idPrefix}-${name}`;
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-text-3">
          Filters{active ? <span className="ml-1.5 text-violet tabular">{active}</span> : null}
        </p>
        <Button size="xs" variant="ghost" onClick={onReset} disabled={!active} className="text-text-3">
          <RotateCcw /> Reset
        </Button>
      </div>

      {!fixedStatus ? (
        <Field label="Status" htmlFor={id("status")}>
          <Select
            value={filters.status ?? ANY}
            onValueChange={(value) => onChange({ status: value === ANY ? null : (value as JobStatus) })}
          >
            <SelectTrigger id={id("status")} className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ANY}>Any status (expired hidden)</SelectItem>
              {JOB_STATUSES.map((status) => (
                <SelectItem key={status} value={status}>
                  {JOB_STATUS[status]?.label ?? status}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
      ) : null}

      <Field label="Source" htmlFor={id("source")}>
        <Select
          value={filters.source ?? ANY}
          onValueChange={(value) => onChange({ source: value === ANY ? null : (value as SourceName) })}
        >
          <SelectTrigger id={id("source")} className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ANY}>Any source</SelectItem>
            {SOURCES.map((source) => (
              <SelectItem key={source} value={source}>
                {SOURCE_LABEL[source]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>

      <Field label="Company" htmlFor={id("company")}>
        <Input
          id={id("company")}
          value={companyText}
          maxLength={200}
          placeholder="Contains…"
          onChange={(event) => onCompanyTextChange(event.target.value)}
        />
      </Field>

      <Field
        label="Minimum score"
        htmlFor={id("min-score")}
        hint={
          <span className="text-xs tabular text-text-1">
            {minScoreDraft === null ? <span className="text-text-3">Any</span> : `≥ ${minScoreDraft}`}
          </span>
        }
      >
        <div className="flex items-center gap-2 pt-1">
          <Slider
            id={id("min-score")}
            aria-label="Minimum match score"
            min={0}
            max={100}
            step={5}
            value={[minScoreDraft ?? 0]}
            onValueChange={([value]) => onMinScoreDraftChange(value === 0 ? null : value)}
            onValueCommit={([value]) => onChange({ min_score: value === 0 ? null : value })}
          />
        </div>
        <p className="text-[11px] text-text-3">Unscored jobs are excluded once a minimum is set.</p>
      </Field>

      <Field label="Posted within" htmlFor={id("age")}>
        <Select
          value={filters.max_age_days === null ? ANY : String(filters.max_age_days)}
          onValueChange={(value) => onChange({ max_age_days: value === ANY ? null : Number(value) })}
        >
          <SelectTrigger id={id("age")} className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ANY}>Any time</SelectItem>
            {[...new Set([...AGE_OPTIONS, ...(filters.max_age_days ? [filters.max_age_days] : [])])]
              .sort((a, b) => a - b)
              .map((days) => (
                <SelectItem key={days} value={String(days)}>
                  {days === 1 ? "Last 24 hours" : `Last ${days} days`}
                </SelectItem>
              ))}
          </SelectContent>
        </Select>
      </Field>

      <div className="flex items-start justify-between gap-3 rounded-lg border border-line bg-surface-2/50 p-2.5">
        <div className="space-y-0.5">
          <Label htmlFor={id("dupes")} className="text-xs font-medium text-text-1">
            Include duplicates
          </Label>
          <p className="text-[11px] leading-snug text-text-3">Show listings merged into another job.</p>
        </div>
        <Switch
          id={id("dupes")}
          checked={filters.include_duplicates}
          onCheckedChange={(checked) => onChange({ include_duplicates: checked })}
        />
      </div>
    </div>
  );
}
