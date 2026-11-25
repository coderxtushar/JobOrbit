"use client";

import { Check, ChevronsUpDown, FileText } from "lucide-react";
import { useState } from "react";

import { StateBadge } from "@/components/shared/status-badge";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import type { Schemas } from "@/lib/api/client";
import { OUTCOME } from "@/lib/constants/states";
import { cn } from "@/lib/utils";

type Application = Schemas["ApplicationRead"];

const INTERVIEW_OUTCOMES = new Set(["screening", "interviewing", "offer"]);

/** Applications in interview first, then the rest, newest first within each group. */
export function sortForPrep(items: Application[]): { interviewing: Application[]; others: Application[] } {
  const byUpdated = [...items].sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  return {
    interviewing: byUpdated.filter((item) => INTERVIEW_OUTCOMES.has(item.outcome)),
    others: byUpdated.filter((item) => !INTERVIEW_OUTCOMES.has(item.outcome)),
  };
}

export function ApplicationPicker({
  applications,
  selectedId,
  onPick,
  loading,
}: {
  applications: Application[];
  selectedId: number | null;
  onPick: (id: number) => void;
  loading?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const selected = applications.find((item) => item.id === selectedId);
  const { interviewing, others } = sortForPrep(applications);

  const renderItem = (item: Application) => (
    <CommandItem
      key={item.id}
      value={`${item.id} ${item.job_title} ${item.job_company}`}
      onSelect={() => {
        onPick(item.id);
        setOpen(false);
      }}
      className="gap-2"
    >
      <Check className={cn("size-3.5", item.id === selectedId ? "opacity-100 text-violet" : "opacity-0")} />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm">{item.job_title || "Untitled role"}</span>
        <span className="block truncate text-[11px] text-text-3">{item.job_company || "Company not stated"}</span>
      </span>
      <StateBadge value={item.outcome} map={OUTCOME} />
    </CommandItem>
  );

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          role="combobox"
          aria-expanded={open}
          aria-label="Pick an application"
          disabled={loading}
          className="h-10 w-full justify-between gap-2 px-3 text-left font-normal sm:w-[24rem]"
        >
          <span className="flex min-w-0 items-center gap-2">
            <FileText className="size-4 text-text-3" />
            <span className={cn("truncate", selected ? "text-text-1" : "text-text-3")}>
              {selected
                ? `${selected.job_title} · ${selected.job_company}`
                : selectedId
                  ? `Application #${selectedId}`
                  : loading
                    ? "Loading applications…"
                    : "Pick an application"}
            </span>
          </span>
          <ChevronsUpDown className="size-4 text-text-3" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[min(30rem,calc(100vw-2rem))] p-0" align="start">
        <Command>
          <CommandInput placeholder="Search by role or company…" aria-label="Search applications" />
          <CommandList className="max-h-[22rem]">
            <CommandEmpty>No application matches.</CommandEmpty>
            {interviewing.length ? <CommandGroup heading="In interviews">{interviewing.map(renderItem)}</CommandGroup> : null}
            {others.length ? <CommandGroup heading="Other applications">{others.map(renderItem)}</CommandGroup> : null}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
