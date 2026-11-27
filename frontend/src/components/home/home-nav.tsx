"use client";

import { ArrowRight, Moon, Sun } from "lucide-react";
import { motion, useMotionValueEvent, useScroll } from "motion/react";
import Link from "next/link";
import { useState } from "react";

import { OrbitMark, Wordmark } from "@/components/brand/orbit-mark";
import { useTheme } from "@/hooks/use-theme";
import { cn } from "@/lib/utils";

import { AUTHOR, GithubMark, REPO_URL } from "./github-mark";
import { Container } from "./primitives";

const LINKS = [
  { href: "#pipeline", label: "How it works" },
  { href: "#match", label: "Matching" },
  { href: "#safety", label: "Safety" },
  { href: "#tracking", label: "Tracking" },
];

export function HomeNav({ signInFirst = false }: { signInFirst?: boolean }) {
  const { scrollY } = useScroll();
  const [scrolled, setScrolled] = useState(false);
  const { resolvedTheme, setTheme } = useTheme();
  useMotionValueEvent(scrollY, "change", (value) => setScrolled(value > 24));

  return (
    <header
      className={cn(
        "fixed inset-x-0 top-0 z-40 transition-[background-color,border-color,backdrop-filter] duration-300",
        scrolled
          ? "border-b border-line bg-background/75 backdrop-blur-xl"
          : "border-b border-transparent",
      )}
    >
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-3 focus:z-50 focus:rounded-md focus:bg-surface-2 focus:px-3 focus:py-2 focus:text-sm"
      >
        Skip to content
      </a>
      <Container className="flex h-16 items-center gap-6">
        <Link
          href="/"
          className="flex items-center gap-2.5 rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <OrbitMark />
          <Wordmark />
        </Link>
        <nav
          aria-label="Sections"
          className="ml-6 hidden items-center gap-1 md:flex"
        >
          {LINKS.map((link) => (
            <a
              key={link.href}
              href={link.href}
              className="group relative rounded-md px-3 py-2 text-[13px] font-medium text-text-2 transition-colors hover:text-text-1"
            >
              {link.label}
              <span className="absolute inset-x-3 bottom-1 h-px origin-left scale-x-0 bg-violet transition-transform duration-300 group-hover:scale-x-100" />
            </a>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-2">
          <a
            href={REPO_URL}
            target="_blank"
            rel="noreferrer"
            aria-label={`JobOrbit on GitHub, by ${AUTHOR.name}`}
            className="group inline-flex h-10 items-center gap-2 rounded-lg px-2.5 text-[13px] font-medium text-text-2 transition-[color,background-color,transform] duration-200 hover:-translate-y-0.5 hover:bg-surface-2 hover:text-text-1 active:translate-y-0 active:scale-[0.97]"
          >
            <GithubMark className="size-[18px] transition-transform duration-300 group-hover:rotate-[8deg]" />
            <span className="hidden lg:inline">{AUTHOR.name}</span>
          </a>
          <button
            type="button"
            aria-label="Toggle light and dark theme"
            onClick={() =>
              setTheme(resolvedTheme === "dark" ? "light" : "dark")
            }
            className="grid size-10 place-items-center rounded-lg text-text-2 transition-colors hover:bg-surface-2 hover:text-text-1"
          >
            <Sun className="hidden size-4 dark:block" />
            <Moon className="size-4 dark:hidden" />
          </button>
          <motion.div whileHover={{ y: -1 }} whileTap={{ scale: 0.97 }}>
            <Link
              href={signInFirst ? "/signin" : "/dashboard"}
              className="group inline-flex h-10 items-center gap-1.5 whitespace-nowrap rounded-lg bg-text-1 px-4 text-[13px] font-semibold text-background transition-[transform,opacity] duration-200 hover:-translate-y-0.5 hover:opacity-90 active:translate-y-0 active:scale-[0.97]"
            >
              <span className="hidden sm:inline">{signInFirst ? "Sign in" : "Open the dashboard"}</span>
              <span className="sm:hidden">{signInFirst ? "Sign in" : "Dashboard"}</span>
              <ArrowRight className="size-3.5 transition-transform group-hover:translate-x-0.5" />
            </Link>
          </motion.div>
        </div>
      </Container>
    </header>
  );
}
