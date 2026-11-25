"use client";

import { X } from "lucide-react";
import { useId, useState } from "react";

import { cn } from "@/lib/utils";

/**
 * A list of short strings edited as chips. Enter or comma adds the typed value, Backspace on
 * an empty field removes the last chip, and pasting a comma- or newline-separated list adds
 * each item. Duplicates (case-insensitive) are ignored.
 */
export function TagInput({
  id,
  value,
  onChange,
  placeholder = "Type and press Enter",
  invalid,
  className,
  describedBy,
  maxItems,
}: {
  id?: string;
  value: string[];
  onChange: (next: string[]) => void;
  placeholder?: string;
  invalid?: boolean;
  className?: string;
  describedBy?: string;
  maxItems?: number;
}) {
  const fallbackId = useId();
  const inputId = id ?? fallbackId;
  const [draft, setDraft] = useState("");

  const add = (raw: string) => {
    const items = raw
      .split(/[,\n]/)
      .map((item) => item.trim())
      .filter(Boolean);
    if (!items.length) return;
    const seen = new Set(value.map((item) => item.toLowerCase()));
    const next = [...value];
    for (const item of items) {
      if (seen.has(item.toLowerCase())) continue;
      if (maxItems && next.length >= maxItems) break;
      seen.add(item.toLowerCase());
      next.push(item);
    }
    onChange(next);
    setDraft("");
  };

  const remove = (index: number) => onChange(value.filter((_, i) => i !== index));

  return (
    <div
      className={cn(
        "flex min-h-9 w-full flex-wrap items-center gap-1.5 rounded-lg border border-input bg-transparent px-2 py-1.5 transition-colors focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/50 dark:bg-input/30",
        invalid && "border-destructive ring-3 ring-destructive/20",
        className,
      )}
      onClick={() => document.getElementById(inputId)?.focus()}
    >
      {value.map((item, index) => (
        <span
          key={`${item}-${index}`}
          className="inline-flex max-w-full items-center gap-1 rounded-md bg-surface-3 py-0.5 pr-1 pl-2 text-xs text-text-1 ring-1 ring-inset ring-line-strong"
        >
          <span className="truncate">{item}</span>
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation();
              remove(index);
            }}
            className="grid size-4 place-items-center rounded text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1 focus-visible:outline-2"
            aria-label={`Remove ${item}`}
          >
            <X className="size-3" />
          </button>
        </span>
      ))}
      <input
        id={inputId}
        value={draft}
        aria-invalid={invalid || undefined}
        aria-describedby={describedBy}
        onChange={(event) => {
          const next = event.target.value;
          if (next.includes(",")) add(next);
          else setDraft(next);
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            add(draft);
          } else if (event.key === "Backspace" && !draft && value.length) {
            remove(value.length - 1);
          }
        }}
        onBlur={() => add(draft)}
        onPaste={(event) => {
          const text = event.clipboardData.getData("text");
          if (/[,\n]/.test(text)) {
            event.preventDefault();
            add(text);
          }
        }}
        placeholder={value.length ? "" : placeholder}
        className="h-6 min-w-[8rem] flex-1 bg-transparent text-sm text-text-1 outline-none placeholder:text-muted-foreground focus-visible:outline-none"
      />
    </div>
  );
}
