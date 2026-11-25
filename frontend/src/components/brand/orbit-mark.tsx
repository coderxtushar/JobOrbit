import { useId } from "react";

import { cn } from "@/lib/utils";

/** The JobOrbit mark: a tilted orbit with a satellite, drawn so it reads at 20px. */
export function OrbitMark({ className }: { className?: string }) {
  // Unique per instance: a gradient defined inside a hidden copy (the desktop sidebar on a
  // phone) cannot be referenced by a visible one.
  const gradient = useId();
  return (
    <svg viewBox="0 0 32 32" aria-hidden className={cn("size-7", className)}>
      <defs>
        <linearGradient id={gradient} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="var(--violet)" />
          <stop offset="100%" stopColor="var(--cyan)" />
        </linearGradient>
      </defs>
      <circle cx="16" cy="16" r="5.5" fill={`url(#${gradient})`} />
      <ellipse
        cx="16"
        cy="16"
        rx="13"
        ry="6"
        fill="none"
        stroke={`url(#${gradient})`}
        strokeWidth="1.8"
        transform="rotate(-28 16 16)"
        opacity="0.9"
      />
      <circle cx="27" cy="10.4" r="2.1" fill="var(--cyan)" />
    </svg>
  );
}

export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={cn("font-heading text-[15px] font-semibold tracking-tight text-text-1", className)}>
      Job<span className="text-violet">Orbit</span>
    </span>
  );
}
