"use client";

import { Check, Moon, PanelLeftClose, Sun } from "lucide-react";

import { useSidebarCollapsed } from "@/components/layout/sidebar-state";
import { SectionHeading } from "@/components/shared/page-header";
import { Surface } from "@/components/shared/surface";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { useTheme, type Theme } from "@/hooks/use-theme";
import { cn } from "@/lib/utils";

/**
 * Theme and layout preferences. Both live in this browser only; the backend has no
 * per-user settings. The selected theme card is styled with `dark:` variants rather than
 * by branching on the theme value, so the server render and first client render agree.
 */
export function AppearanceSettings() {
  const { theme, setTheme } = useTheme();
  const [collapsed, setCollapsed] = useSidebarCollapsed();

  const options: { value: Theme; label: string; icon: typeof Moon; selected: string; preview: string }[] = [
    {
      value: "dark",
      label: "Dark",
      icon: Moon,
      // Selected when <html> has .dark.
      selected: "border-line dark:border-violet dark:shadow-glow",
      preview: "bg-[oklch(0.16_0.02_275)]",
    },
    {
      value: "light",
      label: "Light",
      icon: Sun,
      selected: "border-violet shadow-glow dark:border-line dark:shadow-none",
      preview: "bg-[oklch(0.98_0.004_275)]",
    },
  ];

  return (
    <Surface className="p-5">
      <SectionHeading title="Appearance" description="Remembered in this browser. Nothing here is sent to the API." />
      <div className="grid gap-3 sm:grid-cols-2">
        {options.map((option) => (
          <button
            key={option.value}
            type="button"
            onClick={() => setTheme(option.value)}
            aria-pressed={theme === option.value}
            className={cn(
              "group relative overflow-hidden rounded-xl border bg-surface-2/40 p-3 text-left outline-none transition-[border-color,box-shadow] duration-200 hover:border-line-strong focus-visible:ring-2 focus-visible:ring-ring",
              option.selected,
            )}
          >
            <div className={cn("relative h-20 overflow-hidden rounded-lg border border-line", option.preview)}>
              <div
                className={cn(
                  "absolute inset-y-0 left-0 w-1/4 border-r",
                  option.value === "dark" ? "border-white/10 bg-white/5" : "border-black/10 bg-black/[0.03]",
                )}
              />
              <div className="absolute left-[32%] right-3 top-3 space-y-1.5">
                <div className="h-2 w-1/2 rounded-full bg-violet/70" />
                <div className={cn("h-1.5 w-4/5 rounded-full", option.value === "dark" ? "bg-white/15" : "bg-black/10")} />
                <div className={cn("h-1.5 w-3/5 rounded-full", option.value === "dark" ? "bg-white/10" : "bg-black/[0.07]")} />
                <div className="mt-2 h-4 w-2/5 rounded-md bg-cyan/50" />
              </div>
            </div>
            <div className="mt-2.5 flex items-center justify-between">
              <span className="flex items-center gap-2 text-sm font-medium text-text-1">
                <option.icon className="size-4 text-text-2" /> {option.label}
              </span>
              <span
                className={cn(
                  "grid size-5 place-items-center rounded-full bg-violet text-primary-foreground transition-opacity",
                  option.value === "dark" ? "opacity-0 dark:opacity-100" : "opacity-100 dark:opacity-0",
                )}
                aria-hidden
              >
                <Check className="size-3" />
              </span>
            </div>
          </button>
        ))}
      </div>

      <div className="mt-5 flex items-start justify-between gap-4 border-t border-line pt-4">
        <div className="flex items-start gap-3">
          <PanelLeftClose className="mt-0.5 size-4 shrink-0 text-text-3" />
          <div>
            <Label htmlFor="sidebar-collapsed" className="text-sm font-medium text-text-1">
              Collapse the sidebar
            </Label>
            <p className="mt-0.5 text-xs leading-relaxed text-text-3">
              Shows icons only on wide screens; the button at the bottom of the sidebar does the same. On narrow screens the
              navigation opens from the menu button instead.
            </p>
          </div>
        </div>
        <Switch id="sidebar-collapsed" checked={collapsed} onCheckedChange={setCollapsed} />
      </div>
    </Surface>
  );
}
