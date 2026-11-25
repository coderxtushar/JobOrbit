import { cn } from "@/lib/utils";
import type { Tone } from "@/lib/constants/states";

const TONE_CLASSES: Record<Tone, string> = {
  neutral: "bg-surface-3/70 text-text-2 ring-line-strong",
  violet: "bg-violet-soft text-violet ring-violet/25",
  cyan: "bg-cyan-soft text-cyan ring-cyan/25",
  success: "bg-success-soft text-success ring-success/25",
  warning: "bg-warning-soft text-warning ring-warning/25",
  danger: "bg-danger-soft text-danger ring-danger/25",
};

const DOT_CLASSES: Record<Tone, string> = {
  neutral: "bg-text-3",
  violet: "bg-violet",
  cyan: "bg-cyan",
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-danger",
};

export function StatusBadge({
  tone = "neutral",
  children,
  dot = true,
  className,
}: {
  tone?: Tone;
  children: React.ReactNode;
  dot?: boolean;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-0.5 text-[11.5px] font-medium ring-1 ring-inset",
        TONE_CLASSES[tone],
        className,
      )}
    >
      {dot ? <span className={cn("size-1.5 rounded-full", DOT_CLASSES[tone])} /> : null}
      {children}
    </span>
  );
}

/** Look a value up in one of the state maps in lib/constants/states and render it. */
export function StateBadge({
  value,
  map,
  className,
}: {
  value: string | null | undefined;
  map: Record<string, { label: string; tone: Tone }>;
  className?: string;
}) {
  if (!value) return null;
  const entry = map[value] ?? { label: value.replace(/_/g, " "), tone: "neutral" as Tone };
  return (
    <StatusBadge tone={entry.tone} className={className}>
      {entry.label}
    </StatusBadge>
  );
}
