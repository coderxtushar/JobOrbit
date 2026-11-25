"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import {
  ArrowDownWideNarrow,
  ArrowUpNarrowWide,
  Bookmark,
  ChevronLeft,
  ChevronRight,
  MousePointerClick,
  PanelLeftClose,
  PanelLeftOpen,
  Rocket,
  Search,
  SearchX,
  SlidersHorizontal,
  Wand2,
  X,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";

import { EmptyState } from "@/components/shared/empty-state";
import { ErrorState } from "@/components/shared/query-state";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupInput } from "@/components/ui/input-group";
import { Kbd } from "@/components/ui/kbd";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { api } from "@/lib/api/endpoints";
import { formatNumber } from "@/lib/formatting";
import { cn } from "@/lib/utils";

import { JobCard, JobCardSkeleton } from "./job-card";
import { JobDetailView } from "./job-detail";
import { JobFilterPanel } from "./job-filters";
import { PAGE_SIZES, SORT_OPTIONS, activeFilterCount, isSaved, toListParams, type JobStatus, type SortBy } from "./job-utils";
import { useDebouncedText, useMediaQuery, useUrlFilters } from "./use-url-filters";
import { usePrepareMany, useSaveJob, useSaveMany } from "./use-job-actions";

/* ---------------- selection bar ---------------- */

function SelectionBar({
  selected,
  onClear,
  showSave,
}: {
  selected: number[];
  onClear: () => void;
  showSave: boolean;
}) {
  const router = useRouter();
  const saveMany = useSaveMany();
  const prepareMany = usePrepareMany();
  const busy = saveMany.running || prepareMany.running;
  return (
    <AnimatePresence>
      {selected.length ? (
        <motion.div
          initial={{ opacity: 0, y: 16, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 16, scale: 0.98 }}
          transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
          className="orbit-glass sticky bottom-4 z-20 mx-auto flex w-fit max-w-full flex-wrap items-center gap-2 rounded-xl px-3 py-2 shadow-raised"
          role="region"
          aria-label="Bulk actions for selected jobs"
        >
          <span className="px-1 text-[13px] font-medium text-text-1 tabular">
            {selected.length} selected
          </span>
          <span aria-hidden className="h-5 w-px bg-line-strong" />
          {showSave ? (
            <Button size="sm" variant="outline" disabled={busy} onClick={() => saveMany.run(selected)}>
              <Bookmark /> {saveMany.running ? "Saving…" : "Save"}
            </Button>
          ) : null}
          <Tooltip>
            <TooltipTrigger asChild>
              <Button size="sm" variant="outline" disabled={busy} onClick={() => prepareMany.run(selected)}>
                <Wand2 /> {prepareMany.running ? "Preparing…" : "Prepare selected"}
              </Button>
            </TooltipTrigger>
            <TooltipContent className="max-w-60">
              Drafts an application for each job, one at a time. Nothing is submitted.
            </TooltipContent>
          </Tooltip>
          <Button
            size="sm"
            disabled={busy}
            onClick={() => router.push(`/auto-apply?jobs=${selected.join(",")}`)}
          >
            <Rocket /> Open in auto-apply preflight
          </Button>
          <Button size="icon-sm" variant="ghost" onClick={onClear} disabled={busy} aria-label="Clear selection">
            <X />
          </Button>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}

/* ---------------- pager ---------------- */

function Pager({
  total,
  limit,
  offset,
  onOffset,
  onLimit,
}: {
  total: number;
  limit: number;
  offset: number;
  onOffset: (offset: number) => void;
  onLimit: (limit: number) => void;
}) {
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + limit, total);
  const page = Math.floor(offset / limit) + 1;
  const pages = Math.max(1, Math.ceil(total / limit));
  return (
    <nav className="flex flex-wrap items-center justify-between gap-3 pt-1" aria-label="Pagination">
      <p className="text-xs text-text-3 tabular">
        {formatNumber(from)}–{formatNumber(to)} of {formatNumber(total)} · page {page} of {formatNumber(pages)}
      </p>
      <div className="flex items-center gap-2">
        <Select value={String(limit)} onValueChange={(value) => onLimit(Number(value))}>
          <SelectTrigger size="sm" aria-label="Jobs per page">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {[...new Set([...PAGE_SIZES, limit])].sort((a, b) => a - b).map((size) => (
              <SelectItem key={size} value={String(size)}>
                {size} per page
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button
          size="sm"
          variant="outline"
          disabled={offset === 0}
          onClick={() => onOffset(Math.max(0, offset - limit))}
        >
          <ChevronLeft /> Previous
        </Button>
        <Button size="sm" variant="outline" disabled={to >= total} onClick={() => onOffset(offset + limit)}>
          Next <ChevronRight />
        </Button>
      </div>
    </nav>
  );
}

/* ---------------- browser ---------------- */

/**
 * Search, filter panel, job list and job detail. Used by /jobs (every status) and /saved
 * (fixed to SHORTLISTED). Filters and the open job live in the URL.
 */
export function JobBrowser({
  fixedStatus,
  emptyState,
}: {
  fixedStatus?: JobStatus;
  emptyState?: React.ReactNode;
}) {
  const { filters, update, reset, selectedId, setSelectedId } = useUrlFilters(fixedStatus);
  const isWide = useMediaQuery("(min-width: 1280px)");
  const [filtersOpen, setFiltersOpen] = useState(true);
  const [mobileFilters, setMobileFilters] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(() => new Set());

  const commitSearch = useCallback((value: string) => update({ search: value }), [update]);
  const commitCompany = useCallback((value: string) => update({ company: value }), [update]);
  const [searchText, setSearchText] = useDebouncedText(filters.search, commitSearch);
  const [companyText, setCompanyText] = useDebouncedText(filters.company, commitCompany, 400);

  // Slider drag is local; the URL only changes on release.
  const [minScoreDraft, setMinScoreDraft] = useState(filters.min_score);
  const [syncedMinScore, setSyncedMinScore] = useState(filters.min_score);
  if (filters.min_score !== syncedMinScore) {
    setSyncedMinScore(filters.min_score);
    setMinScoreDraft(filters.min_score);
  }

  const params = toListParams(filters);
  const jobs = useQuery({
    queryKey: ["jobs", params],
    queryFn: () => api.jobs(params),
    placeholderData: keepPreviousData,
  });
  const save = useSaveJob();

  const items = jobs.data?.items ?? [];
  const pageIds = items.map((job) => job.id);
  const pageChecked = pageIds.length > 0 && pageIds.every((id) => selected.has(id));
  const pageIndeterminate = !pageChecked && pageIds.some((id) => selected.has(id));
  const activeCount = activeFilterCount(filters, fixedStatus);
  const hasQuery = activeCount > 0 || filters.search.trim() !== "";

  const toggle = (id: number, on: boolean) =>
    setSelected((current) => {
      const next = new Set(current);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  const togglePage = (on: boolean) =>
    setSelected((current) => {
      const next = new Set(current);
      for (const id of pageIds) {
        if (on) next.add(id);
        else next.delete(id);
      }
      return next;
    });

  const filterPanel = (prefix: string) => (
    <JobFilterPanel
      idPrefix={prefix}
      filters={filters}
      onChange={update}
      onReset={() => {
        setCompanyText("");
        reset();
      }}
      companyText={companyText}
      onCompanyTextChange={setCompanyText}
      minScoreDraft={minScoreDraft}
      onMinScoreDraftChange={setMinScoreDraft}
      fixedStatus={fixedStatus}
    />
  );

  const selectedIds = [...selected];
  const showSave = fixedStatus !== "SHORTLISTED" && items.some((job) => selected.has(job.id) && !isSaved(job));

  return (
    <div className="space-y-4">
      {/* search header */}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <InputGroup className="h-10 flex-1 rounded-xl bg-surface-1 shadow-card">
          <InputGroupAddon>
            <Search className="text-text-3" />
          </InputGroupAddon>
          <InputGroupInput
            aria-label="Search jobs"
            placeholder={fixedStatus ? "Search saved jobs by title, company or skill…" : "Search title, company, location or skill…"}
            value={searchText}
            maxLength={200}
            onChange={(event) => setSearchText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Escape" && searchText) setSearchText("");
            }}
            className="text-sm"
          />
          {searchText ? (
            <InputGroupAddon align="inline-end">
              <InputGroupButton size="icon-xs" aria-label="Clear search" onClick={() => setSearchText("")}>
                <X />
              </InputGroupButton>
            </InputGroupAddon>
          ) : (
            <InputGroupAddon align="inline-end" className="hidden sm:flex">
              <Kbd>Esc</Kbd>
            </InputGroupAddon>
          )}
        </InputGroup>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            className="h-10 lg:hidden"
            onClick={() => setMobileFilters(true)}
            aria-label="Open filters"
          >
            <SlidersHorizontal /> Filters
            {activeCount ? <span className="text-violet tabular">{activeCount}</span> : null}
          </Button>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="outline"
                size="icon-lg"
                className="hidden size-10 lg:inline-flex"
                onClick={() => setFiltersOpen((open) => !open)}
                aria-label={filtersOpen ? "Hide filters" : "Show filters"}
                aria-pressed={filtersOpen}
              >
                {filtersOpen ? <PanelLeftClose /> : <PanelLeftOpen />}
              </Button>
            </TooltipTrigger>
            <TooltipContent>{filtersOpen ? "Hide filters" : "Show filters"}</TooltipContent>
          </Tooltip>
          <Select value={filters.sort_by} onValueChange={(value) => update({ sort_by: value as SortBy })}>
            <SelectTrigger className="h-10! min-w-40 rounded-xl" aria-label="Sort by">
              <span className="text-text-3">Sort</span>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {SORT_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="outline"
                size="icon-lg"
                className="size-10"
                onClick={() => update({ descending: !filters.descending })}
                aria-label={filters.descending ? "Sorted descending; switch to ascending" : "Sorted ascending; switch to descending"}
              >
                {filters.descending ? <ArrowDownWideNarrow /> : <ArrowUpNarrowWide />}
              </Button>
            </TooltipTrigger>
            <TooltipContent>{filters.descending ? "Descending" : "Ascending"}</TooltipContent>
          </Tooltip>
        </div>
      </div>

      <div
        className={cn(
          "grid items-start gap-5",
          filtersOpen
            ? "lg:grid-cols-[15rem_minmax(0,1fr)] xl:grid-cols-[14.5rem_minmax(0,1fr)_minmax(0,28rem)]"
            : "xl:grid-cols-[minmax(0,1fr)_minmax(0,30rem)]",
        )}
      >
        {/* filter panel */}
        {filtersOpen ? (
          <aside
            className="orbit-card sticky top-[calc(var(--topbar-height)+1rem)] hidden p-4 lg:block"
            aria-label="Job filters"
          >
            {filterPanel("desktop")}
          </aside>
        ) : null}

        {/* list */}
        <section className="min-w-0 space-y-3" aria-label="Jobs">
          <div className="flex items-center justify-between gap-3 px-1">
            <label className="flex items-center gap-2 text-xs text-text-2">
              <Checkbox
                checked={pageChecked ? true : pageIndeterminate ? "indeterminate" : false}
                onCheckedChange={(value) => togglePage(value === true)}
                disabled={!items.length}
                aria-label="Select every job on this page"
              />
              Select page
            </label>
            <p className="text-xs text-text-3 tabular" aria-live="polite">
              {jobs.data ? (
                <>
                  <span className="font-medium text-text-1">{formatNumber(jobs.data.total)}</span>{" "}
                  {jobs.data.total === 1 ? "job" : "jobs"}
                  {hasQuery ? " match" : ""}
                </>
              ) : jobs.isLoading ? (
                "Loading…"
              ) : null}
              {jobs.isFetching && !jobs.isLoading ? <span className="ml-2 animate-pulse-soft text-violet">updating</span> : null}
            </p>
          </div>

          {jobs.isLoading ? (
            <div className="space-y-2.5">
              {Array.from({ length: 6 }, (_, index) => (
                <JobCardSkeleton key={index} />
              ))}
            </div>
          ) : jobs.isError ? (
            <ErrorState error={jobs.error} onRetry={() => jobs.refetch()} />
          ) : items.length === 0 ? (
            hasQuery ? (
              <EmptyState
                icon={SearchX}
                title="No jobs match"
                description="Nothing fits this search and these filters. Loosen a filter or clear the search."
                action={
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      setSearchText("");
                      setCompanyText("");
                      update({
                        search: "",
                        status: fixedStatus ?? null,
                        source: null,
                        company: "",
                        min_score: null,
                        max_age_days: null,
                        include_duplicates: false,
                      });
                    }}
                  >
                    Clear search and filters
                  </Button>
                }
              />
            ) : (
              emptyState
            )
          ) : (
            <div className={cn("space-y-2.5 transition-opacity", jobs.isPlaceholderData && "opacity-60")}>
              {items.map((job, index) => (
                <JobCard
                  key={job.id}
                  job={job}
                  index={index}
                  active={job.id === selectedId}
                  checked={selected.has(job.id)}
                  onCheckedChange={(on) => toggle(job.id, on)}
                  onOpen={() => setSelectedId(job.id)}
                  onSave={() => save.mutate(job.id)}
                  saving={save.isPending && save.variables === job.id}
                />
              ))}
            </div>
          )}

          {jobs.data && jobs.data.total > 0 ? (
            <Pager
              total={jobs.data.total}
              limit={filters.limit}
              offset={filters.offset}
              onOffset={(offset) => {
                update({ offset });
                window.scrollTo({ top: 0, behavior: "smooth" });
              }}
              onLimit={(limit) => update({ limit })}
            />
          ) : null}

          <SelectionBar selected={selectedIds} onClear={() => setSelected(new Set())} showSave={showSave} />
        </section>

        {/* detail panel (wide screens) */}
        {isWide ? (
          <aside
            className="orbit-card sticky top-[calc(var(--topbar-height)+1rem)] max-h-[calc(100dvh-var(--topbar-height)-2rem)] overflow-y-auto overscroll-contain p-5"
            aria-label="Job detail"
          >
            <AnimatePresence mode="wait" initial={false}>
              <motion.div
                key={selectedId ?? "none"}
                initial={{ opacity: 0, x: 8 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -8 }}
                transition={{ duration: 0.18, ease: [0.22, 1, 0.36, 1] }}
              >
                {selectedId ? (
                  <div className="space-y-2">
                    <div className="-mt-1 flex justify-end">
                      <Button size="icon-xs" variant="ghost" onClick={() => setSelectedId(null)} aria-label="Close job detail">
                        <X />
                      </Button>
                    </div>
                    <JobDetailView jobId={selectedId} variant="panel" />
                  </div>
                ) : (
                  <EmptyState
                    compact
                    icon={MousePointerClick}
                    title="Pick a job"
                    description="Select a job to see its match analysis, the evidence behind it and the full listing."
                    className="border-none"
                  />
                )}
              </motion.div>
            </AnimatePresence>
          </aside>
        ) : null}
      </div>

      {/* filters sheet (narrow screens) */}
      <Sheet open={mobileFilters} onOpenChange={setMobileFilters}>
        <SheetContent side="left" className="w-[88vw] overflow-y-auto data-[side=left]:sm:max-w-sm">
          <SheetHeader className="pb-0">
            <SheetTitle>Filters</SheetTitle>
            <SheetDescription>Only filters the jobs API supports.</SheetDescription>
          </SheetHeader>
          <div className="px-4 pb-6">{filterPanel("mobile")}</div>
        </SheetContent>
      </Sheet>

      {/* detail sheet (narrow screens) */}
      <Sheet open={!isWide && selectedId !== null} onOpenChange={(open) => (!open ? setSelectedId(null) : undefined)}>
        <SheetContent side="right" className="w-full overflow-y-auto data-[side=right]:sm:max-w-xl">
          <SheetHeader className="sr-only">
            <SheetTitle>Job detail</SheetTitle>
            <SheetDescription>Listing, match analysis and actions for the selected job.</SheetDescription>
          </SheetHeader>
          <div className="p-5 pt-10">{selectedId !== null ? <JobDetailView jobId={selectedId} variant="panel" /> : null}</div>
        </SheetContent>
      </Sheet>
    </div>
  );
}
