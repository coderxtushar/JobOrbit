import { cn } from "@/lib/utils";

/**
 * Decorative orbital rings for hero areas. Pure SVG and CSS rotation (no JS), slow enough
 * to read as ambience, and switched off by prefers-reduced-motion in globals.css.
 */
export function OrbitBackdrop({ className }: { className?: string }) {
  return (
    <div aria-hidden className={cn("pointer-events-none absolute inset-0 overflow-hidden", className)}>
      <div className="absolute -right-24 -top-40 size-[34rem] opacity-70">
        <svg viewBox="0 0 400 400" className="size-full animate-orbit-spin">
          <ellipse cx="200" cy="200" rx="190" ry="78" fill="none" stroke="var(--violet)" strokeOpacity="0.22" transform="rotate(-24 200 200)" />
          <circle cx="372" cy="124" r="4" fill="var(--violet)" opacity="0.8" />
        </svg>
      </div>
      <div className="absolute -right-10 -top-24 size-[26rem] opacity-70">
        <svg viewBox="0 0 400 400" className="size-full animate-orbit-spin-reverse">
          <ellipse cx="200" cy="200" rx="185" ry="110" fill="none" stroke="var(--cyan)" strokeOpacity="0.18" transform="rotate(18 200 200)" />
          <circle cx="40" cy="250" r="3" fill="var(--cyan)" opacity="0.9" />
        </svg>
      </div>
      <div className="absolute right-24 top-6 size-40 rounded-full bg-violet/20 blur-3xl" />
      <div className="absolute right-64 top-28 size-24 rounded-full bg-cyan/10 blur-2xl" />
    </div>
  );
}
