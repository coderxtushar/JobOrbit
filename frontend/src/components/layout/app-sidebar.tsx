"use client";

import Link from "next/link";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";

import { OrbitMark, Wordmark } from "@/components/brand/orbit-mark";
import { NavLinks } from "@/components/navigation/nav-links";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useHealth } from "@/hooks/use-health";
import { cn } from "@/lib/utils";

import { useSidebarCollapsed } from "./sidebar-state";

export function AppSidebar() {
  const [collapsed, setCollapsed] = useSidebarCollapsed();
  const health = useHealth();
  const online = health.isSuccess;

  return (
    <aside
      className={cn(
        "sticky top-0 hidden h-dvh shrink-0 flex-col border-r border-sidebar-border bg-sidebar transition-[width] duration-300 ease-[var(--ease-orbit)] lg:flex",
        collapsed ? "w-[var(--sidebar-width-collapsed)]" : "w-[var(--sidebar-width)]",
      )}
    >
      <div className={cn("flex h-[var(--topbar-height)] items-center gap-2.5 px-4", collapsed && "justify-center px-0")}>
        <Link href="/dashboard" className="flex items-center gap-2.5 rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring">
          <OrbitMark />
          {collapsed ? null : (
            <div className="leading-tight">
              <Wordmark />
              <p className="text-[10.5px] text-text-3">Personal workspace</p>
            </div>
          )}
        </Link>
      </div>
      <ScrollArea className="min-h-0 flex-1">
        <div className={cn("px-3 py-3", collapsed && "px-2")}>
          <NavLinks collapsed={collapsed} />
        </div>
      </ScrollArea>
      <div className={cn("flex items-center gap-2 border-t border-sidebar-border p-3", collapsed && "flex-col")}>
        <div
          className={cn("flex min-w-0 flex-1 items-center gap-2 text-[11.5px] text-text-3", collapsed && "justify-center")}
          title={online ? `API ${health.data?.version ?? ""}` : "API offline"}
        >
          <span
            className={cn(
              "size-2 shrink-0 rounded-full",
              health.isLoading ? "bg-text-3" : online ? "bg-success shadow-[0_0_8px_var(--success)]" : "bg-danger",
            )}
          />
          {collapsed ? null : (
            <span className="truncate">
              {health.isLoading ? "Connecting…" : online ? `API online · v${health.data?.version}` : "API offline"}
            </span>
          )}
        </div>
        <button
          type="button"
          onClick={() => setCollapsed(!collapsed)}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          className="grid size-8 place-items-center rounded-md text-text-3 transition-colors hover:bg-sidebar-accent hover:text-text-1"
        >
          {collapsed ? <PanelLeftOpen className="size-4" /> : <PanelLeftClose className="size-4" />}
        </button>
      </div>
    </aside>
  );
}
