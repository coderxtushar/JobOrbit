"use client";

import { X } from "lucide-react";
import { useId, useState } from "react";

import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

/** Label, control, hint and error for one form field. */
export function Field({
  label,
  htmlFor,
  hint,
  error,
  children,
  className,
  aside,
}: {
  label: string;
  htmlFor?: string;
  hint?: React.ReactNode;
  error?: string;
  children: React.ReactNode;
  className?: string;
  aside?: React.ReactNode;
}) {
  return (
    <div className={cn("flex min-w-0 flex-col gap-1.5", className)}>
      <div className="flex items-center justify-between gap-2">
        <Label htmlFor={htmlFor} className="text-xs font-medium text-text-2">
          {label}
        </Label>
        {aside}
      </div>
      {children}
      {error ? (
        <p role="alert" className="text-[11.5px] text-danger">
          {error}
        </p>
      ) : hint ? (
        <p className="text-[11.5px] leading-snug text-text-3">{hint}</p>
      ) : null}
    </div>
  );
}

/**
 * Multi-select as a row of pressable chips. Each chip is a real toggle button
 * (aria-pressed), reachable with Tab and switched with Space or Enter.
 */
export function ChipToggleGroup({
  options,
  value,
  onChange,
  label,
  className,
}: {
  options: { value: string; label: string }[];
  value: string[];
  onChange: (next: string[]) => void;
  label: string;
  className?: string;
}) {
  return (
    <div role="group" aria-label={label} className={cn("flex flex-wrap gap-1.5", className)}>
      {options.map((option) => {
        const on = value.includes(option.value);
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={on}
            onClick={() =>
              onChange(on ? value.filter((item) => item !== option.value) : [...value, option.value])
            }
            className={cn(
              "h-7 rounded-full border px-2.5 text-xs font-medium transition-[background-color,border-color,color,box-shadow] duration-150",
              on
                ? "border-violet/40 bg-violet-soft text-violet shadow-[0_0_0_1px_var(--violet-soft)]"
                : "border-line-strong bg-surface-2/50 text-text-2 hover:border-line-strong hover:bg-surface-3 hover:text-text-1",
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

/** One choice out of a few, as a segmented control (radio semantics). */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (next: T) => void;
  label: string;
}) {
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className="inline-flex h-8 w-full items-center gap-0.5 rounded-lg border border-line-strong bg-surface-2/50 p-0.5"
    >
      {options.map((option) => {
        const on = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={on}
            onClick={() => onChange(option.value)}
            className={cn(
              "h-full flex-1 rounded-md px-2 text-xs font-medium capitalize transition-colors duration-150",
              on ? "bg-surface-3 text-text-1 shadow-sm" : "text-text-3 hover:text-text-1",
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

/**
 * Free-text list as chips: type and press Enter or comma to add, Backspace on an empty
 * input removes the last one. Pasting "a, b, c" adds three.
 */
export function ChipInput({
  value,
  onChange,
  placeholder,
  id,
  ariaLabel,
}: {
  value: string[];
  onChange: (next: string[]) => void;
  placeholder?: string;
  id?: string;
  ariaLabel?: string;
}) {
  const [draft, setDraft] = useState("");
  const fallbackId = useId();
  const inputId = id ?? fallbackId;

  const commit = (text: string) => {
    const parts = text
      .split(",")
      .map((part) => part.trim())
      .filter(Boolean);
    if (!parts.length) return;
    const seen = new Set(value.map((item) => item.toLowerCase()));
    const additions = parts.filter((part) => {
      const key = part.toLowerCase();
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
    if (additions.length) onChange([...value, ...additions]);
    setDraft("");
  };

  return (
    <div
      className="flex min-h-8 w-full flex-wrap items-center gap-1 rounded-lg border border-input bg-transparent px-1.5 py-1 transition-colors focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/50 dark:bg-input/30"
      onClick={() => document.getElementById(inputId)?.focus()}
    >
      {value.map((item) => (
        <span
          key={item}
          className="inline-flex h-6 items-center gap-1 rounded-md bg-surface-3 pl-2 pr-1 text-xs text-text-1"
        >
          {item}
          <button
            type="button"
            aria-label={`Remove ${item}`}
            onClick={(event) => {
              event.stopPropagation();
              onChange(value.filter((entry) => entry !== item));
            }}
            className="grid size-4 place-items-center rounded text-text-3 hover:bg-surface-2 hover:text-text-1"
          >
            <X className="size-3" />
          </button>
        </span>
      ))}
      <input
        id={inputId}
        aria-label={ariaLabel}
        value={draft}
        placeholder={value.length ? "" : placeholder}
        onChange={(event) => {
          const next = event.target.value;
          if (next.includes(",")) commit(next);
          else setDraft(next);
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            commit(draft);
          } else if (event.key === "Backspace" && !draft && value.length) {
            onChange(value.slice(0, -1));
          }
        }}
        onBlur={() => commit(draft)}
        className="h-6 min-w-[8rem] flex-1 bg-transparent px-1 text-sm text-text-1 outline-none placeholder:text-muted-foreground"
      />
    </div>
  );
}

/** Pill marking a hard constraint, so it is never mistaken for a ranking preference. */
export function HardConstraintTag() {
  return (
    <span className="rounded-full bg-warning-soft px-1.5 py-px text-[10px] font-semibold uppercase tracking-wider text-warning ring-1 ring-inset ring-warning/25">
      Hard
    </span>
  );
}
