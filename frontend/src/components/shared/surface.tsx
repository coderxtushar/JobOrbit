import { cn } from "@/lib/utils";

/** The standard content card. `interactive` adds the hover lift used by clickable cards. */
export function Surface({
  className,
  interactive,
  children,
  ...props
}: React.HTMLAttributes<HTMLDivElement> & { interactive?: boolean }) {
  return (
    <div
      className={cn(
        "orbit-card",
        interactive &&
          "transition-[border-color,box-shadow,transform] duration-200 ease-[var(--ease-orbit)] hover:-translate-y-px hover:border-line-strong hover:shadow-raised",
        className,
      )}
      {...props}
    >
      {children}
    </div>
  );
}
