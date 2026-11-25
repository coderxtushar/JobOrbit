"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { motion } from "motion/react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useNavCounts } from "@/hooks/use-nav-counts";
import { NAVIGATION } from "@/lib/constants/navigation";
import { cn } from "@/lib/utils";

export function NavLinks({ collapsed = false, onNavigate }: { collapsed?: boolean; onNavigate?: () => void }) {
  const pathname = usePathname();
  const counts = useNavCounts();

  return (
    <nav aria-label="Main" className="flex flex-col gap-5">
      {NAVIGATION.map((group) => (
        <div key={group.label} className="flex flex-col gap-0.5">
          {collapsed ? (
            <div className="mx-auto mb-1 h-px w-6 bg-line" />
          ) : (
            <p className="px-3 pb-1 text-[10.5px] font-semibold uppercase tracking-[0.14em] text-text-3">
              {group.label}
            </p>
          )}
          {group.items.map((item) => {
            const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
            const count = item.count ? counts[item.count] : undefined;
            const Icon = item.icon;
            const link = (
              <Link
                href={item.href}
                onClick={onNavigate}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "group relative flex h-9 items-center gap-3 rounded-lg px-3 text-[13px] font-medium outline-none transition-colors duration-150",
                  "text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:ring-2 focus-visible:ring-ring",
                  active && "text-text-1",
                  collapsed && "justify-center px-0",
                )}
              >
                {active ? (
                  <motion.span
                    layoutId="nav-active"
                    className="absolute inset-0 rounded-lg bg-sidebar-accent ring-1 ring-inset ring-line-strong"
                    transition={{ type: "spring", stiffness: 500, damping: 40 }}
                  />
                ) : null}
                {active ? (
                  <span className="absolute left-0 top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-full bg-violet shadow-[0_0_10px_var(--violet)]" />
                ) : null}
                <Icon
                  className={cn(
                    "relative size-4 shrink-0 transition-colors",
                    active ? "text-violet" : "text-text-3 group-hover:text-text-2",
                  )}
                />
                {collapsed ? null : <span className="relative truncate">{item.title}</span>}
                {count ? (
                  collapsed ? (
                    <span className="absolute right-1.5 top-1.5 size-1.5 rounded-full bg-violet" />
                  ) : (
                    <span className="relative ml-auto rounded-md bg-violet-soft px-1.5 text-[11px] font-semibold text-violet tabular">
                      {count > 99 ? "99+" : count}
                    </span>
                  )
                ) : null}
              </Link>
            );
            return collapsed ? (
              <Tooltip key={item.href}>
                <TooltipTrigger asChild>{link}</TooltipTrigger>
                <TooltipContent side="right">
                  {item.title}
                  {count ? ` · ${count}` : ""}
                </TooltipContent>
              </Tooltip>
            ) : (
              <div key={item.href}>{link}</div>
            );
          })}
        </div>
      ))}
    </nav>
  );
}
