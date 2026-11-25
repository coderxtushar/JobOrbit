import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

/** Shown when there is genuinely nothing yet. Never filled with sample data. */
export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
  compact,
}: {
  icon?: LucideIcon;
  title: string;
  description?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
  compact?: boolean;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center rounded-xl border border-dashed border-line-strong text-center",
        compact ? "gap-2 px-4 py-8" : "gap-3 px-6 py-14",
        className,
      )}
    >
      {Icon ? (
        <div className="relative grid size-11 place-items-center rounded-xl bg-violet-soft text-violet ring-1 ring-inset ring-violet/20">
          <Icon className="size-5" />
        </div>
      ) : null}
      <div className="space-y-1">
        <p className="font-heading text-sm font-semibold text-text-1">{title}</p>
        {description ? <p className="mx-auto max-w-sm text-xs leading-relaxed text-text-3">{description}</p> : null}
      </div>
      {action ? <div className="mt-1">{action}</div> : null}
    </div>
  );
}
