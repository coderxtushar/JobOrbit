"use client";

import { ShieldCheck } from "lucide-react";
import { Controller, useFormContext, type FieldPath } from "react-hook-form";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

import type { ProfileFormValues, TriState } from "./profile-schema";
import { TagInput } from "./tag-input";

type Path = FieldPath<ProfileFormValues>;

/** Reads a nested error message ("education.0.degree") out of the form state. */
function useFieldError(name: Path): string | undefined {
  const { formState, getFieldState } = useFormContext<ProfileFormValues>();
  const state = getFieldState(name, formState);
  return state.error?.message;
}

export function SensitiveMark() {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          tabIndex={0}
          className="inline-flex items-center gap-1 rounded-full bg-warning-soft px-1.5 py-px text-[10.5px] font-medium text-warning ring-1 ring-inset ring-warning/25"
        >
          <ShieldCheck className="size-3" /> Sensitive
        </span>
      </TooltipTrigger>
      <TooltipContent className="max-w-xs text-xs">
        Only you can answer this. JobOrbit never guesses or drafts it; left blank it stays “not stated” and
        applications that ask it wait in the Action inbox.
      </TooltipContent>
    </Tooltip>
  );
}

export function Field({
  name,
  label,
  hint,
  sensitive,
  className,
  children,
}: {
  name: Path;
  label: string;
  hint?: React.ReactNode;
  sensitive?: boolean;
  className?: string;
  children: (props: { id: string; invalid: boolean; describedBy: string }) => React.ReactNode;
}) {
  const error = useFieldError(name);
  const id = `profile-${name.replace(/\./g, "-")}`;
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const describedBy = [hint ? hintId : null, error ? errorId : null].filter(Boolean).join(" ");
  return (
    <div className={cn("space-y-1.5", className)}>
      <div className="flex items-center gap-2">
        <Label htmlFor={id} className="text-[13px] font-medium text-text-1">
          {label}
        </Label>
        {sensitive ? <SensitiveMark /> : null}
      </div>
      {children({ id, invalid: Boolean(error), describedBy })}
      {error ? (
        <p id={errorId} role="alert" className="text-xs text-danger">
          {error}
        </p>
      ) : hint ? (
        <p id={hintId} className="text-xs leading-relaxed text-text-3">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

export function TextField({
  name,
  label,
  hint,
  placeholder,
  type = "text",
  sensitive,
  inputMode,
  className,
  suffix,
}: {
  name: Path;
  label: string;
  hint?: React.ReactNode;
  placeholder?: string;
  type?: string;
  sensitive?: boolean;
  inputMode?: React.HTMLAttributes<HTMLInputElement>["inputMode"];
  className?: string;
  suffix?: string;
}) {
  const { register } = useFormContext<ProfileFormValues>();
  return (
    <Field name={name} label={label} hint={hint} sensitive={sensitive} className={className}>
      {({ id, invalid, describedBy }) => (
        <div className="relative">
          <Input
            id={id}
            type={type}
            inputMode={inputMode}
            placeholder={placeholder}
            aria-invalid={invalid || undefined}
            aria-describedby={describedBy || undefined}
            className={cn("h-9", suffix && "pr-14")}
            {...register(name)}
          />
          {suffix ? (
            <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-xs text-text-3">
              {suffix}
            </span>
          ) : null}
        </div>
      )}
    </Field>
  );
}

export function TextAreaField({
  name,
  label,
  hint,
  placeholder,
  rows = 3,
}: {
  name: Path;
  label: string;
  hint?: React.ReactNode;
  placeholder?: string;
  rows?: number;
}) {
  const { register } = useFormContext<ProfileFormValues>();
  return (
    <Field name={name} label={label} hint={hint}>
      {({ id, invalid, describedBy }) => (
        <Textarea
          id={id}
          rows={rows}
          placeholder={placeholder}
          aria-invalid={invalid || undefined}
          aria-describedby={describedBy || undefined}
          {...register(name)}
        />
      )}
    </Field>
  );
}

export function TagField({
  name,
  label,
  hint,
  placeholder,
}: {
  name: Path;
  label: string;
  hint?: React.ReactNode;
  placeholder?: string;
}) {
  const { control } = useFormContext<ProfileFormValues>();
  return (
    <Field name={name} label={label} hint={hint}>
      {({ id, invalid, describedBy }) => (
        <Controller
          control={control}
          name={name}
          render={({ field }) => (
            <TagInput
              id={id}
              value={(field.value as string[]) ?? []}
              onChange={field.onChange}
              invalid={invalid}
              describedBy={describedBy || undefined}
              placeholder={placeholder}
            />
          )}
        />
      )}
    </Field>
  );
}

/** Multiple choice from a fixed list, as toggle chips. */
export function ChoiceField<T extends string>({
  name,
  label,
  hint,
  options,
}: {
  name: Path;
  label: string;
  hint?: React.ReactNode;
  options: ReadonlyArray<{ value: T; label: string }>;
}) {
  const { control } = useFormContext<ProfileFormValues>();
  return (
    <Field name={name} label={label} hint={hint}>
      {({ id, describedBy }) => (
        <Controller
          control={control}
          name={name}
          render={({ field }) => (
            <ToggleGroup
              id={id}
              type="multiple"
              variant="outline"
              spacing={2}
              value={(field.value as string[]) ?? []}
              onValueChange={field.onChange}
              aria-describedby={describedBy || undefined}
              aria-label={label}
              className="flex-wrap justify-start"
            >
              {options.map((option) => (
                <ToggleGroupItem
                  key={option.value}
                  value={option.value}
                  className="h-8 px-3 text-xs data-[state=on]:border-violet/40 data-[state=on]:bg-violet-soft data-[state=on]:text-violet"
                >
                  {option.label}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          )}
        />
      )}
    </Field>
  );
}

const TRI_OPTIONS: Array<{ value: TriState; label: string }> = [
  { value: "unset", label: "Not stated" },
  { value: "yes", label: "Yes" },
  { value: "no", label: "No" },
];

/** A yes / no question that can also be left unanswered — never defaulted to "no". */
export function TriStateField({
  name,
  label,
  hint,
  sensitive,
}: {
  name: Path;
  label: string;
  hint?: React.ReactNode;
  sensitive?: boolean;
}) {
  const { control } = useFormContext<ProfileFormValues>();
  return (
    <Field name={name} label={label} hint={hint} sensitive={sensitive}>
      {({ id, describedBy }) => (
        <Controller
          control={control}
          name={name}
          render={({ field }) => (
            <ToggleGroup
              id={id}
              type="single"
              variant="outline"
              spacing={0}
              value={field.value as string}
              onValueChange={(next) => {
                if (next) field.onChange(next);
              }}
              aria-describedby={describedBy || undefined}
              aria-label={label}
              className="justify-start"
            >
              {TRI_OPTIONS.map((option) => (
                <ToggleGroupItem
                  key={option.value}
                  value={option.value}
                  className={cn(
                    "h-8 px-3 text-xs",
                    option.value === "unset"
                      ? "data-[state=on]:bg-surface-3 data-[state=on]:text-text-2"
                      : "data-[state=on]:bg-violet-soft data-[state=on]:text-violet",
                  )}
                >
                  {option.label}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          )}
        />
      )}
    </Field>
  );
}

/** Groups related fields inside a section with a quiet heading. */
export function FieldGroup({
  title,
  description,
  children,
  className,
}: {
  title: string;
  description?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <fieldset className={cn("space-y-4", className)}>
      <div>
        <legend className="font-heading text-sm font-semibold text-text-1">{title}</legend>
        {description ? <p className="mt-0.5 text-xs leading-relaxed text-text-3">{description}</p> : null}
      </div>
      {children}
    </fieldset>
  );
}
