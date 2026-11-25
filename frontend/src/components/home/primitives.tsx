"use client";

import { MotionConfig, motion, type Variants } from "motion/react";
import Link from "next/link";
import { useSyncExternalStore } from "react";

import { cn } from "@/lib/utils";

/** The page's one content column: every section shares these left and right edges. */
export function Container({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div className={cn("mx-auto w-full max-w-[76rem] px-5 sm:px-8", className)}>
      {children}
    </div>
  );
}

/** A full-screen chapter. The heading leads, the content sits on the same column. */
export function Chapter({
  id,
  className,
  children,
  label,
  backdrop,
}: {
  id: string;
  className?: string;
  children: React.ReactNode;
  label: string;
  /** Decoration drawn behind the content, across the full width of the section. */
  backdrop?: React.ReactNode;
}) {
  return (
    <section
      id={id}
      aria-label={label}
      className={cn(
        "relative flex min-h-svh scroll-mt-16 items-center py-24 lg:py-28",
        className,
      )}
    >
      {backdrop}
      <Container className="relative">{children}</Container>
    </section>
  );
}

export function Eyebrow({ children }: { children: React.ReactNode }) {
  return (
    <p className="inline-flex items-center gap-2 text-[12px] font-semibold uppercase tracking-[0.18em] text-violet">
      <span className="h-px w-6 bg-violet/60" />
      {children}
    </p>
  );
}

/** Primary and secondary call-to-action, with the hover step and press the page uses everywhere. */
export function CtaLink({
  href,
  children,
  variant = "primary",
  className,
}: {
  href: string;
  children: React.ReactNode;
  variant?: "primary" | "ghost";
  className?: string;
}) {
  return (
    <Link
      href={href}
      className={cn(
        "group inline-flex h-11 items-center justify-center gap-2 rounded-xl px-5 text-sm font-semibold outline-none transition-[transform,box-shadow,background-color,border-color] duration-200 ease-[var(--ease-orbit)] hover:-translate-y-0.5 active:translate-y-0 active:scale-[0.98] focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
        variant === "primary"
          ? "bg-violet text-primary-foreground shadow-glow hover:shadow-[0_0_0_1px_var(--violet),0_14px_44px_-10px_var(--violet)]"
          : "border border-line-strong bg-surface-1/60 text-text-1 backdrop-blur hover:border-violet/40 hover:bg-surface-2",
        className,
      )}
    >
      {children}
    </Link>
  );
}

const REDUCE_QUERY = "(prefers-reduced-motion: reduce)";

function subscribeReduced(onChange: () => void) {
  const query = window.matchMedia(REDUCE_QUERY);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

/**
 * The visitor's reduced-motion setting, but false while hydrating: the server cannot know it,
 * so the first client render matches the HTML and the setting applies right after.
 */
export function useCalmMotion() {
  return useSyncExternalStore(
    subscribeReduced,
    () => window.matchMedia(REDUCE_QUERY).matches,
    () => false,
  );
}

/** Motion's own reduced-motion handling for everything inside: transforms are skipped. */
export function HomeMotion({ children }: { children: React.ReactNode }) {
  return <MotionConfig reducedMotion="user">{children}</MotionConfig>;
}

/** Staggered entrance for the hero, played once on load. */
export function useEnter(): { container: Variants; item: Variants } {
  const reduced = useCalmMotion();
  return {
    container: {
      hidden: {},
      show: {
        transition: { staggerChildren: reduced ? 0 : 0.09, delayChildren: 0.1 },
      },
    },
    item: reduced
      ? { hidden: { opacity: 1 }, show: { opacity: 1 } }
      : {
          hidden: { opacity: 0, y: 18, filter: "blur(8px)" },
          show: {
            opacity: 1,
            y: 0,
            filter: "blur(0px)",
            transition: { duration: 0.7, ease: [0.22, 1, 0.36, 1] },
          },
        },
  };
}

export const MotionDiv = motion.div;
