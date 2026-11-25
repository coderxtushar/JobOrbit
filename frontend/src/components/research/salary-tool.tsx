"use client";

import { useQuery } from "@tanstack/react-query";
import { Calculator, Info, Loader2, Scale } from "lucide-react";
import { useId, useState } from "react";

import { ErrorState } from "@/components/shared/query-state";
import { StatusBadge } from "@/components/shared/status-badge";
import { Surface } from "@/components/shared/surface";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api/endpoints";
import type { Schemas } from "@/lib/api/client";
import { formatNumber, humanize } from "@/lib/formatting";

const CURRENCIES = ["INR", "USD", "EUR", "GBP", "SGD", "AED", "CAD", "AUD"];

const UNIT_LABEL: Record<string, string> = {
  lpa: "Lakh per annum (LPA)",
  inr_annual: "INR per year",
  inr_monthly: "INR per month",
  usd_annual: "USD per year",
};

function amount(value: number | null | undefined, currency: string | null | undefined) {
  if (value === null || value === undefined) return "—";
  return `${currency ? `${currency} ` : ""}${formatNumber(Math.round(value))}`;
}

function range(min: number | null | undefined, max: number | null | undefined, currency: string | null | undefined) {
  if (min == null && max == null) return "—";
  if (min != null && max != null && min !== max) return `${amount(min, currency)} – ${formatNumber(Math.round(max))}`;
  return amount(min ?? max, currency);
}

function Assumptions({ items }: { items: string[] }) {
  if (!items.length) return <p className="text-xs text-text-3">No assumptions were needed.</p>;
  return (
    <ul className="space-y-1">
      {items.map((item, index) => (
        <li key={index} className="flex gap-1.5 text-xs leading-relaxed text-text-2">
          <Info className="mt-0.5 size-3 shrink-0 text-warning" aria-hidden />
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}

function CompensationSummary({ comp }: { comp: Schemas["CompensationRead"] }) {
  if (!comp.disclosed) {
    return <p className="text-sm text-text-3 italic">No salary amount was found in this text: not stated.</p>;
  }
  const rows: [string, React.ReactNode][] = [
    [
      "Currency",
      <>
        {comp.currency ?? "—"}{" "}
        <span className="text-text-3">({comp.currency_stated ? "stated" : "assumed"})</span>
      </>,
    ],
    [
      "Period",
      <>
        {comp.period ? humanize(comp.period) : "—"}{" "}
        <span className="text-text-3">({comp.period_stated ? "stated" : "assumed"})</span>
      </>,
    ],
    ["As written", range(comp.minimum, comp.maximum, comp.currency)],
    ["Per year", range(comp.annual_minimum, comp.annual_maximum, comp.currency)],
    ["Per year in INR", range(comp.inr_annual_minimum, comp.inr_annual_maximum, "INR")],
    ["Scale", comp.scale ? humanize(comp.scale) : "—"],
  ];
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
      {rows.map(([label, value]) => (
        <div key={label} className="contents">
          <dt className="text-xs text-text-3">{label}</dt>
          <dd className="tabular text-text-1">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function ParseResult({ result }: { result: Schemas["SalaryParseRead"] }) {
  const { compensation, proposals } = result;
  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-text-3">Parsed</p>
        <CompensationSummary comp={compensation} />
      </div>
      <div className="space-y-2">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-text-3">Assumptions made</p>
        <Assumptions items={compensation.assumptions} />
      </div>
      <div className="space-y-2">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-text-3">
          What a form asking in each unit would receive
        </p>
        <ul className="space-y-2">
          {Object.entries(proposals).map(([unit, proposal]) => (
            <li key={unit} className="rounded-lg border border-line p-3">
              <div className="flex items-center justify-between gap-2">
                <p className="text-xs text-text-2">{UNIT_LABEL[unit] ?? humanize(unit)}</p>
                {proposal.value ? (
                  <span className="flex items-center gap-1.5">
                    <span className="tabular font-heading text-sm font-semibold text-text-1">
                      {/^\d+(\.\d+)?$/.test(proposal.value) ? formatNumber(Number(proposal.value)) : proposal.value}
                    </span>
                    <StatusBadge tone={proposal.exact ? "success" : "warning"} dot={false}>
                      {proposal.exact ? "exact" : "approximate"}
                    </StatusBadge>
                  </span>
                ) : (
                  <span className="text-xs text-text-3 italic">Not proposed</span>
                )}
              </div>
              {proposal.assumptions.length ? (
                <details className="group mt-2">
                  <summary className="cursor-pointer text-[11px] text-text-3 hover:text-text-1">
                    {proposal.assumptions.length} assumption{proposal.assumptions.length === 1 ? "" : "s"}
                  </summary>
                  <div className="mt-1.5">
                    <Assumptions items={proposal.assumptions} />
                  </div>
                </details>
              ) : null}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function JobSalaryComparison({ jobId, onUseText }: { jobId: number; onUseText: (text: string) => void }) {
  const salary = useQuery({
    queryKey: ["research", "job-salary", jobId],
    queryFn: () => api.jobSalary(jobId),
  });
  if (salary.isPending) return <Skeleton className="h-24 w-full" />;
  if (salary.isError) return <ErrorState error={salary.error} onRetry={() => salary.refetch()} />;
  const { listing, expectation, comparison, listing_source } = salary.data;
  return (
    <div className="space-y-3 rounded-lg border border-line bg-surface-2/40 p-3">
      <div className="flex items-center gap-2">
        <Scale className="size-3.5 text-cyan" />
        <p className="text-xs font-medium text-text-1">This listing vs your expectation</p>
      </div>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
        <dt className="text-xs text-text-3">Listing</dt>
        <dd className="tabular text-text-1">
          {listing.disclosed ? (
            range(listing.annual_minimum, listing.annual_maximum, listing.currency)
          ) : (
            <span className="text-text-3 italic">not stated</span>
          )}
          {listing.disclosed && listing_source ? (
            <span className="ml-1 text-[11px] text-text-3">({humanize(listing_source)})</span>
          ) : null}
        </dd>
        <dt className="text-xs text-text-3">Your expectation</dt>
        <dd className="tabular text-text-1">
          {expectation.disclosed ? (
            range(expectation.annual_minimum, expectation.annual_maximum, expectation.currency)
          ) : (
            <span className="text-text-3 italic">not set in your profile</span>
          )}
        </dd>
      </dl>
      <p className="text-xs leading-relaxed text-text-2">{comparison.statement}</p>
      {listing.original ? (
        <Button size="xs" variant="outline" onClick={() => onUseText(listing.original)}>
          Parse the listing&apos;s salary text
        </Button>
      ) : null}
    </div>
  );
}

/**
 * Salary text → structured compensation, with every assumption spelled out. Pure: the
 * endpoint writes nothing, and a unit it cannot convert to is reported as not proposed.
 */
export function SalaryTool({ jobId }: { jobId: number | null }) {
  const id = useId();
  const [text, setText] = useState("");
  const [currency, setCurrency] = useState("INR");
  const [submitted, setSubmitted] = useState<{ text: string; currency: string } | null>(null);

  const parsed = useQuery({
    queryKey: ["research", "salary-parse", submitted?.text, submitted?.currency],
    queryFn: () => api.parseSalary(submitted!.text, submitted!.currency),
    enabled: Boolean(submitted?.text),
    staleTime: Infinity,
  });

  const submit = (value = text) => {
    const trimmed = value.trim();
    if (!trimmed) return;
    setSubmitted({ text: trimmed, currency });
  };

  return (
    <Surface className="space-y-4 p-4 sm:p-5">
      <header className="flex items-start gap-2.5">
        <span className="grid size-7 shrink-0 place-items-center rounded-lg bg-cyan-soft text-cyan ring-1 ring-inset ring-cyan/20">
          <Calculator className="size-3.5" />
        </span>
        <div>
          <h2 className="font-heading text-sm font-semibold text-text-1">Salary reader</h2>
          <p className="mt-0.5 text-xs text-text-3">
            Paste salary text as written (“12–18 LPA”, “$120k–150k”, “₹80,000/month”). Every assumption is shown.
          </p>
        </div>
      </header>

      {jobId ? (
        <JobSalaryComparison
          jobId={jobId}
          onUseText={(value) => {
            setText(value);
            submit(value);
          }}
        />
      ) : null}

      <form
        className="space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <div className="space-y-1.5">
          <Label htmlFor={`${id}-text`}>Salary text</Label>
          <Input
            id={`${id}-text`}
            value={text}
            maxLength={500}
            onChange={(event) => setText(event.target.value)}
            placeholder="e.g. 12-18 LPA"
            autoComplete="off"
          />
        </div>
        <div className="flex items-end gap-2">
          <div className="flex-1 space-y-1.5">
            <Label htmlFor={`${id}-currency`}>Currency when the text does not say</Label>
            <Select value={currency} onValueChange={setCurrency}>
              <SelectTrigger id={`${id}-currency`} className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {CURRENCIES.map((code) => (
                  <SelectItem key={code} value={code}>
                    {code}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Button type="submit" disabled={!text.trim() || parsed.isFetching}>
            {parsed.isFetching ? <Loader2 className="animate-spin" /> : null}
            Read
          </Button>
        </div>
      </form>

      {submitted ? (
        parsed.isPending ? (
          <div className="space-y-2">
            <Skeleton className="h-4 w-2/3" />
            <Skeleton className="h-4 w-1/2" />
            <Skeleton className="h-20 w-full" />
          </div>
        ) : parsed.isError ? (
          <ErrorState error={parsed.error} onRetry={() => parsed.refetch()} />
        ) : (
          <ParseResult result={parsed.data} />
        )
      ) : null}
    </Surface>
  );
}
