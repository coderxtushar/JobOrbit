"use client";

import type { LucideIcon } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

import { AnimatedNumber } from "./animated-number";

type Accent = "violet" | "cyan" | "success" | "warning" | "danger" | "neutral";

const ACCENT: Record<Accent, string> = {
  violet: "text-violet bg-violet-soft ring-violet/20",
  cyan: "text-cyan bg-cyan-soft ring-cyan/20",
  success: "text-success bg-success-soft ring-success/20",
  warning: "text-warning bg-warning-soft ring-warning/20",
  danger: "text-danger bg-danger-soft ring-danger/20",
  neutral: "text-text-2 bg-surface-3 ring-line-strong",
};

/**
 * One headline figure. `value` null means "not available" and renders an em dash with the
 * reason, never a zero: missing data and zero are different facts.
 */
export function KpiCard({
  label,
  value,
  caption,
  icon: Icon,
  accent = "violet",
  loading,
  suffix,
  className,
}: {
  label: string;
  value: number | null | undefined;
  caption?: string;
  icon?: LucideIcon;
  accent?: Accent;
  loading?: boolean;
  suffix?: string;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "orbit-card group relative overflow-hidden p-4 transition-[border-color,box-shadow] duration-200 hover:border-line-strong",
        className,
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <p className="text-xs font-medium text-text-2">{label}</p>
        {Icon ? (
          <span className={cn("grid size-7 place-items-center rounded-lg ring-1 ring-inset", ACCENT[accent])}>
            <Icon className="size-3.5" />
          </span>
        ) : null}
      </div>
      <div className="mt-2.5 font-heading text-[28px] font-semibold leading-none tracking-tight text-text-1 tabular">
        {loading ? (
          <Skeleton className="h-7 w-16" />
        ) : value === null || value === undefined ? (
          <span className="text-text-3">—</span>
        ) : (
          <>
            <AnimatedNumber value={value} />
            {suffix ? <span className="ml-0.5 text-base text-text-3">{suffix}</span> : null}
          </>
        )}
      </div>
      {caption ? <p className="mt-2 text-[11.5px] leading-snug text-text-3">{caption}</p> : null}
      <div className="pointer-events-none absolute inset-x-0 bottom-0 h-px bg-gradient-to-r from-transparent via-violet/40 to-transparent opacity-0 transition-opacity duration-300 group-hover:opacity-100" />
    </div>
  );
}
