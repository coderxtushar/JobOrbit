"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Moon, Octagon, Radar, Sparkles, Sun, Target } from "lucide-react";
import { useTheme } from "@/hooks/use-theme";
import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
  CommandShortcut,
} from "@/components/ui/command";
import { errorMessage } from "@/components/shared/query-state";
import { api } from "@/lib/api/endpoints";
import { NAVIGATION } from "@/lib/constants/navigation";

const PaletteContext = createContext<{ open: () => void }>({ open: () => {} });

export function useCommandPalette() {
  return useContext(PaletteContext);
}

/**
 * Cmd/Ctrl+K. Navigation to every page, plus the actions the backend genuinely supports:
 * scoring, discovery and the emergency stop. Each action reports the backend's real answer.
 */
export function CommandPaletteProvider({ children }: { children: React.ReactNode }) {
  const [isOpen, setOpen] = useState(false);
  const router = useRouter();
  const queryClient = useQueryClient();
  const { resolvedTheme, setTheme } = useTheme();

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen((value) => !value);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const score = useMutation({
    mutationFn: () => api.scoreJobs({ rescore_all: false, offset: 0 }),
    onSuccess: (result) => {
      toast.success(`Scored ${result.scored} job(s)`, {
        description: `${result.high} strong · ${result.review} worth a look · ${result.filtered_out} filtered out`,
      });
      queryClient.invalidateQueries();
    },
    onError: (error) => toast.error("Scoring failed", { description: errorMessage(error) }),
  });
  const discover = useMutation({
    mutationFn: () => api.discoverJobs({ trigger: "manual" }),
    onSuccess: (runs) => {
      const created = runs.reduce((sum, run) => sum + (run.jobs_created ?? 0), 0);
      toast.success(`Discovery finished: ${created} new job(s)`, {
        description: `${runs.length} source(s) checked`,
      });
      queryClient.invalidateQueries();
    },
    onError: (error) => toast.error("Discovery failed", { description: errorMessage(error) }),
  });
  const stop = useMutation({
    mutationFn: () => api.emergencyStop("from the command palette"),
    onSuccess: () => {
      toast.warning("Emergency stop is on", { description: "Every run is cancelled until you clear it." });
      queryClient.invalidateQueries();
    },
    onError: (error) => toast.error("Could not stop runs", { description: errorMessage(error) }),
  });

  const run = useCallback((action: () => void) => {
    setOpen(false);
    action();
  }, []);

  const value = useMemo(() => ({ open: () => setOpen(true) }), []);

  return (
    <PaletteContext.Provider value={value}>
      {children}
      <CommandDialog
        open={isOpen}
        onOpenChange={setOpen}
        title="Command palette"
        description="Go to a page or run an action"
        className="sm:max-w-xl"
      >
        <CommandInput placeholder="Search pages and actions…" />
        <CommandList className="max-h-[min(60vh,28rem)]">
          <CommandEmpty>Nothing matches.</CommandEmpty>
          <CommandGroup heading="Actions">
            <CommandItem onSelect={() => run(() => router.push("/auto-apply"))} keywords={["preflight", "apply"]}>
              <Target /> Build an auto-apply preflight
            </CommandItem>
            <CommandItem onSelect={() => run(() => discover.mutate())} keywords={["fetch", "boards"]}>
              <Radar /> Run job discovery
            </CommandItem>
            <CommandItem onSelect={() => run(() => score.mutate())} keywords={["rank", "match"]}>
              <Sparkles /> Score new jobs
            </CommandItem>
            <CommandItem
              onSelect={() => run(() => setTheme(resolvedTheme === "dark" ? "light" : "dark"))}
              keywords={["theme", "dark", "light"]}
            >
              {resolvedTheme === "dark" ? <Sun /> : <Moon />} Switch to {resolvedTheme === "dark" ? "light" : "dark"} theme
            </CommandItem>
            <CommandItem
              onSelect={() => run(() => stop.mutate())}
              keywords={["halt", "cancel", "panic"]}
              className="text-danger data-[selected=true]:text-danger"
            >
              <Octagon /> Emergency stop all runs
            </CommandItem>
          </CommandGroup>
          <CommandSeparator />
          {NAVIGATION.map((group) => (
            <CommandGroup key={group.label} heading={group.label}>
              {group.items.map((item) => (
                <CommandItem
                  key={item.href}
                  value={`${item.title} ${item.description}`}
                  keywords={item.keywords}
                  onSelect={() => run(() => router.push(item.href))}
                >
                  <item.icon />
                  <span>{item.title}</span>
                  <CommandShortcut className="hidden text-[11px] normal-case tracking-normal sm:inline">
                    {item.description}
                  </CommandShortcut>
                </CommandItem>
              ))}
            </CommandGroup>
          ))}
        </CommandList>
      </CommandDialog>
    </PaletteContext.Provider>
  );
}
