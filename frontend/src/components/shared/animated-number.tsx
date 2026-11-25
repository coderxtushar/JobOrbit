"use client";

import { animate, useReducedMotion } from "motion/react";
import { useEffect, useState } from "react";

import { formatNumber } from "@/lib/formatting";

/**
 * Counts up to `value` once, on load. It animates straight away rather than when scrolled
 * into view, so a counter below the fold is never left showing a false 0. The real value
 * is always exposed to assistive technology, and shown directly when motion is reduced.
 */
export function AnimatedNumber({
  value,
  format = formatNumber,
  className,
}: {
  value: number;
  format?: (value: number) => string;
  className?: string;
}) {
  const reduced = useReducedMotion();
  const [current, setCurrent] = useState(0);

  useEffect(() => {
    if (reduced) return;
    const controls = animate(0, value, {
      duration: 0.9,
      ease: [0.22, 1, 0.36, 1],
      onUpdate: (latest) => setCurrent(Math.round(latest)),
    });
    return () => controls.stop();
  }, [reduced, value]);

  return (
    <span className={className} aria-label={format(value)}>
      <span aria-hidden>{format(reduced ? value : current)}</span>
    </span>
  );
}
