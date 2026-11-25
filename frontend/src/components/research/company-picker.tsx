"use client";

import { useQuery } from "@tanstack/react-query";
import { Building2, Briefcase, ChevronsUpDown, Loader2, Search } from "lucide-react";
import { useDeferredValue, useMemo, useState } from "react";

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
import { api } from "@/lib/api/endpoints";
import type { Schemas } from "@/lib/api/client";
import { cn } from "@/lib/utils";

export type CompanySelection = { job: number } | { company: string };

/**
 * Search the jobs JobOrbit holds and pick either one listing (research plus that job's
 * requirements) or the company alone. Results come from `/api/jobs?search=`, so only
 * companies that actually appear in your listings can be picked.
 */
export function CompanyPicker({
  label,
  onPick,
  className,
}: {
  label: string | null;
  onPick: (selection: CompanySelection) => void;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const deferred = useDeferredValue(search.trim());

  const jobs = useQuery({
    queryKey: ["jobs", "research-picker", deferred],
    queryFn: () => api.jobs({ search: deferred, limit: 30 }),
    enabled: open && deferred.length >= 2,
    staleTime: 30_000,
  });

  const groups = useMemo(() => {
    const map = new Map<string, Schemas["JobRead"][]>();
    for (const job of jobs.data?.items ?? []) {
      const key = job.company || "Company not stated";
      map.set(key, [...(map.get(key) ?? []), job]);
    }
    return [...map.entries()];
  }, [jobs.data]);

  const pick = (selection: CompanySelection) => {
    onPick(selection);
    setOpen(false);
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          role="combobox"
          aria-expanded={open}
          aria-label="Pick a company from your jobs"
          className={cn("h-10 w-full justify-between gap-2 px-3 text-left font-normal sm:w-[26rem]", className)}
        >
          <span className="flex min-w-0 items-center gap-2">
            <Search className="size-4 text-text-3" />
            <span className={cn("truncate", label ? "text-text-1" : "text-text-3")}>
              {label ?? "Search a company or job title from your listings"}
            </span>
          </span>
          <ChevronsUpDown className="size-4 text-text-3" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[min(32rem,calc(100vw-2rem))] p-0" align="start">
        <Command shouldFilter={false}>
          <CommandInput
            value={search}
            onValueChange={setSearch}
            placeholder="Company or job title…"
            aria-label="Search your jobs"
          />
          <CommandList className="max-h-[22rem]">
            {deferred.length < 2 ? (
              <p className="px-3 py-6 text-center text-xs text-text-3">Type at least two characters.</p>
            ) : jobs.isFetching && !jobs.data ? (
              <p className="flex items-center justify-center gap-2 px-3 py-6 text-xs text-text-3">
                <Loader2 className="size-3.5 animate-spin" /> Searching your listings…
              </p>
            ) : jobs.isError ? (
              <p className="px-3 py-6 text-center text-xs text-danger">Search failed. Try again.</p>
            ) : (
              <>
                <CommandEmpty>No job in your listings matches “{deferred}”.</CommandEmpty>
                {groups.map(([company, items]) => (
                  <CommandGroup key={company} heading={company}>
                    {items[0]?.company ? (
                      <CommandItem
                        value={`company:${company}`}
                        onSelect={() => pick({ company: items[0].company })}
                        className="gap-2"
                      >
                        <Building2 className="size-4 text-violet" />
                        <span className="truncate">Research {company}</span>
                        <span className="ml-auto text-[11px] text-text-3">company only</span>
                      </CommandItem>
                    ) : null}
                    {items.slice(0, 5).map((job) => (
                      <CommandItem
                        key={job.id}
                        value={`job:${job.id}`}
                        onSelect={() => pick({ job: job.id })}
                        className="gap-2"
                      >
                        <Briefcase className="size-4 text-text-3" />
                        <span className="truncate">{job.title}</span>
                        <span className="ml-auto max-w-[9rem] truncate text-[11px] text-text-3">
                          {job.location || "location not stated"}
                        </span>
                      </CommandItem>
                    ))}
                  </CommandGroup>
                ))}
              </>
            )}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
