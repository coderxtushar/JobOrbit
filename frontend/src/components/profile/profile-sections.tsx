"use client";

import { GraduationCap, Plus, Trash2, FolderGit2 } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { Controller, useFieldArray, useFormContext, useWatch } from "react-hook-form";

import { EmptyState } from "@/components/shared/empty-state";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { formatSalary, humanize } from "@/lib/formatting";

import {
  ChoiceField,
  Field,
  FieldGroup,
  TagField,
  TextField,
  TriStateField,
} from "./form-fields";
import {
  CURRENCIES,
  EMPLOYMENT_TYPES,
  EXPERIENCE_LEVELS,
  WORK_ARRANGEMENTS,
  type ProfileFormValues,
} from "./profile-schema";
import { TagInput } from "./tag-input";

const LEVEL_LABEL: Record<(typeof EXPERIENCE_LEVELS)[number], string> = {
  fresher: "Fresher",
  junior: "Junior",
  mid: "Mid-level",
  senior: "Senior",
  lead: "Lead",
};

const rise = {
  initial: { opacity: 0, y: 6 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -4 },
  transition: { duration: 0.2, ease: [0.22, 1, 0.36, 1] as const },
};

export function IdentitySection() {
  return (
    <div className="space-y-8">
      <FieldGroup title="Who you are" description="Used on every application form JobOrbit prepares.">
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField name="full_name" label="Full name" placeholder="As it appears on your resume" />
          <TextField name="email" label="Email" type="email" placeholder="you@example.com" />
          <TextField name="phone" label="Phone" type="tel" placeholder="+91 …" />
        </div>
        <TextField
          name="headline"
          label="Headline"
          placeholder="e.g. Backend engineer focused on Python and distributed systems"
          hint="One line about you. At most 300 characters."
        />
      </FieldGroup>
      <FieldGroup title="Links" description="Portfolio, GitHub, LinkedIn. Full URLs, one per chip.">
        <TagField name="links" label="Links" placeholder="https://github.com/you — press Enter to add" />
      </FieldGroup>
    </div>
  );
}

export function ExperienceSection() {
  const { control } = useFormContext<ProfileFormValues>();
  return (
    <div className="space-y-8">
      <FieldGroup title="Experience" description="The matcher compares this with what each listing asks for.">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field name="experience_level" label="Experience level">
            {({ id, invalid, describedBy }) => (
              <Controller
                control={control}
                name="experience_level"
                render={({ field }) => (
                  <Select value={field.value} onValueChange={field.onChange}>
                    <SelectTrigger
                      id={id}
                      aria-invalid={invalid || undefined}
                      aria-describedby={describedBy || undefined}
                      className="h-9 w-full"
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {EXPERIENCE_LEVELS.map((level) => (
                        <SelectItem key={level} value={level}>
                          {LEVEL_LABEL[level]}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              />
            )}
          </Field>
          <TextField
            name="years_experience"
            label="Years of experience"
            inputMode="decimal"
            suffix="years"
            hint="Decimals are fine, e.g. 1.5."
          />
        </div>
      </FieldGroup>
      <FieldGroup title="What you are looking for">
        <TagField
          name="target_titles"
          label="Target titles"
          placeholder="e.g. Backend Developer"
          hint="Job titles you would apply for. Title match is part of every score."
        />
      </FieldGroup>
      <FieldGroup title="Skills" description="Only list what you can talk about in an interview; resume variants never add skills that are not here or on your resume.">
        <TagField name="technical_skills" label="Technical skills" placeholder="e.g. python, react, postgresql" />
        <TagField name="soft_skills" label="Soft skills" placeholder="e.g. mentoring" />
      </FieldGroup>
    </div>
  );
}

export function BackgroundSection() {
  const { control, register, formState } = useFormContext<ProfileFormValues>();
  const education = useFieldArray({ control, name: "education" });
  const projects = useFieldArray({ control, name: "projects" });
  const errors = formState.errors;

  return (
    <div className="space-y-10">
      <FieldGroup title="Education">
        <AnimatePresence initial={false}>
          {education.fields.map((entry, index) => (
            <motion.div
              key={entry.id}
              {...rise}
              className="rounded-xl border border-line bg-surface-2/40 p-4"
            >
              <div className="mb-3 flex items-center justify-between gap-2">
                <p className="flex items-center gap-2 text-xs font-medium text-text-2">
                  <GraduationCap className="size-3.5 text-violet" /> Education {index + 1}
                </p>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  onClick={() => education.remove(index)}
                  aria-label={`Remove education ${index + 1}`}
                >
                  <Trash2 />
                </Button>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                {(
                  [
                    ["degree", "Degree", "e.g. Bachelor of Technology"],
                    ["institution", "Institution", ""],
                    ["field_of_study", "Field of study", "e.g. Computer Science"],
                    ["grade", "Grade", "e.g. 8.2 CGPA"],
                    ["start_year", "Start year", "e.g. 2022"],
                    ["end_year", "End year", "e.g. 2026"],
                  ] as const
                ).map(([key, label, placeholder]) => {
                  const id = `education-${index}-${key}`;
                  const message = errors.education?.[index]?.[key]?.message;
                  return (
                    <div key={key} className="space-y-1.5">
                      <Label htmlFor={id} className="text-xs text-text-2">
                        {label}
                      </Label>
                      <Input
                        id={id}
                        placeholder={placeholder}
                        aria-invalid={message ? true : undefined}
                        className="h-9"
                        {...register(`education.${index}.${key}`)}
                      />
                      {message ? <p className="text-xs text-danger">{message}</p> : null}
                    </div>
                  );
                })}
              </div>
            </motion.div>
          ))}
        </AnimatePresence>
        {education.fields.length === 0 ? (
          <EmptyState compact icon={GraduationCap} title="No education recorded" description="Add it here, or copy it from your resume's parsed fields." />
        ) : null}
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() =>
            education.append({ degree: "", institution: "", field_of_study: "", start_year: "", end_year: "", grade: "" })
          }
        >
          <Plus /> Add education
        </Button>
        <TextField
          name="graduation_date"
          label="Graduation date"
          placeholder="e.g. 2026 or 2026-05"
          hint="Some forms ask for it separately. Left blank it stays not stated."
          className="max-w-xs"
        />
      </FieldGroup>

      <FieldGroup title="Projects" description="Interview prep and resume variants quote these. Describe what you actually built.">
        <AnimatePresence initial={false}>
          {projects.fields.map((entry, index) => {
            const err = errors.projects?.[index];
            return (
              <motion.div key={entry.id} {...rise} className="rounded-xl border border-line bg-surface-2/40 p-4">
                <div className="mb-3 flex items-center justify-between gap-2">
                  <p className="flex items-center gap-2 text-xs font-medium text-text-2">
                    <FolderGit2 className="size-3.5 text-cyan" /> Project {index + 1}
                  </p>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    onClick={() => projects.remove(index)}
                    aria-label={`Remove project ${index + 1}`}
                  >
                    <Trash2 />
                  </Button>
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="space-y-1.5">
                    <Label htmlFor={`project-${index}-name`} className="text-xs text-text-2">
                      Name
                    </Label>
                    <Input
                      id={`project-${index}-name`}
                      className="h-9"
                      aria-invalid={err?.name ? true : undefined}
                      {...register(`projects.${index}.name`)}
                    />
                    {err?.name?.message ? <p className="text-xs text-danger">{err.name.message}</p> : null}
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor={`project-${index}-url`} className="text-xs text-text-2">
                      URL
                    </Label>
                    <Input
                      id={`project-${index}-url`}
                      className="h-9"
                      placeholder="https://"
                      aria-invalid={err?.url ? true : undefined}
                      {...register(`projects.${index}.url`)}
                    />
                    {err?.url?.message ? <p className="text-xs text-danger">{err.url.message}</p> : null}
                  </div>
                  <div className="space-y-1.5 sm:col-span-2">
                    <Label htmlFor={`project-${index}-description`} className="text-xs text-text-2">
                      Description
                    </Label>
                    <textarea
                      id={`project-${index}-description`}
                      rows={3}
                      className="w-full rounded-lg border border-input bg-transparent px-2.5 py-2 text-sm outline-none transition-colors placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
                      {...register(`projects.${index}.description`)}
                    />
                  </div>
                  <div className="space-y-1.5 sm:col-span-2">
                    <Label htmlFor={`project-${index}-tech`} className="text-xs text-text-2">
                      Technologies
                    </Label>
                    <Controller
                      control={control}
                      name={`projects.${index}.technologies`}
                      render={({ field }) => (
                        <TagInput id={`project-${index}-tech`} value={field.value ?? []} onChange={field.onChange} placeholder="e.g. fastapi" />
                      )}
                    />
                  </div>
                </div>
              </motion.div>
            );
          })}
        </AnimatePresence>
        {projects.fields.length === 0 ? (
          <EmptyState compact icon={FolderGit2} title="No projects recorded" description="Without projects there are no project questions in interview prep." />
        ) : null}
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => projects.append({ name: "", description: "", technologies: [], url: "" })}
        >
          <Plus /> Add project
        </Button>
      </FieldGroup>

      <FieldGroup title="Certifications">
        <TagField name="certifications" label="Certifications" placeholder="e.g. AWS Certified Cloud Practitioner" />
      </FieldGroup>
    </div>
  );
}

export function PreferencesSection() {
  return (
    <div className="space-y-8">
      <FieldGroup title="Where and how" description="Used to score location fit. Listings outside these still appear, just lower.">
        <TagField name="preferred_locations" label="Preferred locations" placeholder="e.g. Bengaluru, Remote" />
        <ChoiceField
          name="work_arrangements"
          label="Work arrangements"
          options={WORK_ARRANGEMENTS.map((value) => ({ value, label: humanize(value) }))}
        />
        <ChoiceField
          name="employment_types"
          label="Employment types"
          options={EMPLOYMENT_TYPES.map((value) => ({ value, label: humanize(value) }))}
        />
        <TriStateField
          name="open_to_relocation"
          label="Open to relocation"
          sensitive
          hint="“Not stated” means forms that ask will wait for you; it is never sent as “No”."
        />
      </FieldGroup>
      <FieldGroup title="Leanings" description="Optional. A small boost in the preferences part of the score.">
        <TagField name="preferred_companies" label="Preferred companies" />
        <TagField name="preferred_industries" label="Preferred industries" placeholder="e.g. fintech" />
      </FieldGroup>
    </div>
  );
}

export function CompensationSection() {
  const { control } = useFormContext<ProfileFormValues>();
  const [low, high, currency] = useWatch({
    control,
    name: ["salary_expectation_min", "salary_expectation_max", "salary_currency"],
  });
  const preview = formatSalary(
    low.trim() && Number.isFinite(Number(low)) ? Number(low) : null,
    high.trim() && Number.isFinite(Number(high)) ? Number(high) : null,
    currency,
  );
  const currencies = CURRENCIES.includes(currency as (typeof CURRENCIES)[number]) || !currency ? CURRENCIES : [...CURRENCIES, currency];

  return (
    <div className="space-y-8">
      <div className="rounded-xl border border-warning/25 bg-warning-soft px-4 py-3 text-xs leading-relaxed text-text-2">
        <span className="font-medium text-text-1">These answers are yours alone.</span> JobOrbit never guesses or
        drafts salary, notice period, work authorization or sponsorship. Leave a field blank and it stays
        “not stated”: an application that asks for it waits in the Action inbox instead of being filled in.
      </div>
      <FieldGroup title="Salary expectation" description="Annual amount in the chosen currency. Either bound may be left blank.">
        <div className="grid gap-4 sm:grid-cols-[1fr_1fr_9rem]">
          <TextField name="salary_expectation_min" label="Minimum" inputMode="numeric" placeholder="e.g. 1200000" sensitive />
          <TextField name="salary_expectation_max" label="Maximum" inputMode="numeric" placeholder="e.g. 1800000" />
          <Field name="salary_currency" label="Currency">
            {({ id, invalid }) => (
              <Controller
                control={control}
                name="salary_currency"
                render={({ field }) => (
                  <Select value={field.value} onValueChange={field.onChange}>
                    <SelectTrigger id={id} aria-invalid={invalid || undefined} className="h-9 w-full">
                      <SelectValue placeholder="Currency" />
                    </SelectTrigger>
                    <SelectContent>
                      {currencies.map((code) => (
                        <SelectItem key={code} value={code}>
                          {code}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              />
            )}
          </Field>
        </div>
        <p className="text-xs text-text-3">
          Reads as: <span className="font-medium text-text-2 tabular">{preview || "not stated"}</span>
        </p>
      </FieldGroup>
      <FieldGroup title="Availability and eligibility">
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField
            name="notice_period_days"
            label="Notice period"
            inputMode="numeric"
            suffix="days"
            sensitive
            hint="0 means you can join immediately. Blank means not stated."
          />
          <TextField
            name="work_authorization"
            label="Work authorization"
            sensitive
            placeholder="e.g. Indian citizen"
            hint="In your own words. Blank means not stated."
          />
        </div>
        <TriStateField name="requires_sponsorship" label="Requires visa sponsorship" sensitive />
      </FieldGroup>
    </div>
  );
}

export function FiltersSection() {
  const { control } = useFormContext<ProfileFormValues>();
  return (
    <div className="space-y-8">
      <FieldGroup title="Exclusions" description="Listings that match any of these are filtered out before scoring.">
        <TagField name="excluded_companies" label="Excluded companies" />
        <TagField name="excluded_keywords" label="Excluded keywords" placeholder="e.g. unpaid, commission only" />
      </FieldGroup>
      <FieldGroup title="Thresholds">
        <Field
          name="minimum_match_score"
          label="Minimum match score"
          hint="Jobs below this are not shortlisted or prepared automatically."
        >
          {({ id, invalid, describedBy }) => (
            <Controller
              control={control}
              name="minimum_match_score"
              render={({ field }) => {
                const numeric = Number(field.value);
                const sliderValue = Number.isFinite(numeric) ? Math.max(0, Math.min(100, numeric)) : 0;
                return (
                  <div className="flex items-center gap-4">
                    <Slider
                      value={[sliderValue]}
                      min={0}
                      max={100}
                      step={1}
                      onValueChange={([next]) => field.onChange(String(next))}
                      aria-label="Minimum match score"
                      className="flex-1"
                    />
                    <Input
                      id={id}
                      value={field.value}
                      onChange={(event) => field.onChange(event.target.value)}
                      onBlur={field.onBlur}
                      inputMode="decimal"
                      aria-invalid={invalid || undefined}
                      aria-describedby={describedBy || undefined}
                      className="h-9 w-20 text-center tabular"
                    />
                  </div>
                );
              }}
            />
          )}
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField name="max_job_age_days" label="Maximum job age" inputMode="numeric" suffix="days" hint="Older listings are treated as stale." />
          <TextField
            name="max_required_experience_years"
            label="Maximum required experience"
            inputMode="decimal"
            suffix="years"
            hint="Skip listings asking for more than this. Blank means no limit."
          />
        </div>
      </FieldGroup>
      <FieldGroup title="Hard constraints">
        <Controller
          control={control}
          name="requires_india_work_eligibility"
          render={({ field }) => (
            <label className="flex cursor-pointer items-start justify-between gap-4 rounded-xl border border-line bg-surface-2/40 p-4 transition-colors hover:border-line-strong">
              <span className="space-y-0.5">
                <span className="block text-[13px] font-medium text-text-1">Need jobs I can do from India</span>
                <span className="block text-xs text-text-3">
                  Remote listings restricted to another country or region are filtered out.
                </span>
              </span>
              <Switch checked={field.value} onCheckedChange={field.onChange} aria-label="Need jobs I can do from India" />
            </label>
          )}
        />
      </FieldGroup>
    </div>
  );
}
