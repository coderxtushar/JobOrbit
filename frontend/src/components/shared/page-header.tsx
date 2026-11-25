import { cn } from "@/lib/utils";

export function PageHeader({
  title,
  description,
  actions,
  eyebrow,
  className,
}: {
  title: string;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  eyebrow?: string;
  className?: string;
}) {
  return (
    <header className={cn("flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between", className)}>
      <div className="min-w-0 space-y-1.5">
        {eyebrow ? (
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-violet">{eyebrow}</p>
        ) : null}
        <h1 className="font-heading text-2xl font-semibold tracking-tight text-text-1 sm:text-[28px]">
          {title}
        </h1>
        {description ? <p className="max-w-2xl text-sm leading-relaxed text-text-2">{description}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}

export function SectionHeading({
  title,
  description,
  actions,
}: {
  title: string;
  description?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <div className="mb-3 flex items-end justify-between gap-3">
      <div>
        <h2 className="font-heading text-[15px] font-semibold tracking-tight text-text-1">{title}</h2>
        {description ? <p className="mt-0.5 text-xs text-text-3">{description}</p> : null}
      </div>
      {actions}
    </div>
  );
}
