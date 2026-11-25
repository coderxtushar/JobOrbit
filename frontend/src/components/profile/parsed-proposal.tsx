"use client";

import { ArrowRightToLine, Info } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import type { Schemas } from "@/lib/api/client";
import { cn } from "@/lib/utils";

type Parsed = Schemas["ParsedResumeFields"];

export interface ProposalSelection {
  full_name?: string;
  email?: string;
  phone?: string;
  links?: string[];
  skills?: string[];
  certifications?: string[];
  graduation_date?: string;
  years_experience?: number;
  education?: Schemas["EducationEntry"][];
  projects?: Schemas["ProjectEntry"][];
}

type Key = keyof ProposalSelection;

const s = (value: unknown) => (value === null || value === undefined ? "" : String(value));

function educationOf(parsed: Parsed): Schemas["EducationEntry"][] {
  return ((parsed.education ?? []) as Record<string, unknown>[]).map((entry) => ({
    degree: s(entry.degree) || s(entry.raw),
    institution: s(entry.institution),
    field_of_study: s(entry.field_of_study),
    start_year: s(entry.start_year),
    end_year: s(entry.end_year),
    grade: s(entry.grade),
  }));
}

function projectsOf(parsed: Parsed): Schemas["ProjectEntry"][] {
  return ((parsed.projects ?? []) as Record<string, unknown>[]).map((entry) => ({
    name: s(entry.name),
    description: s(entry.description),
    technologies: Array.isArray(entry.technologies) ? entry.technologies.map(String) : [],
    url: s(entry.url),
  }));
}

function Confidence({ value }: { value: number | undefined }) {
  if (value === undefined) return null;
  const pct = Math.round(value * 100);
  const tone = pct >= 80 ? "text-success" : pct >= 50 ? "text-warning" : "text-danger";
  return (
    <span className={cn("text-[11px] tabular", tone)} title="How sure the parser is about this field">
      {pct}% sure
    </span>
  );
}

function Chips({ items, limit = 18 }: { items: string[]; limit?: number }) {
  if (!items.length) return <span className="text-xs text-text-3 italic">not found</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {items.slice(0, limit).map((item) => (
        <span key={item} className="rounded-md bg-surface-3 px-1.5 py-0.5 text-[11px] text-text-2 ring-1 ring-inset ring-line">
          {item}
        </span>
      ))}
      {items.length > limit ? <span className="px-1 text-[11px] text-text-3">+{items.length - limit} more</span> : null}
    </div>
  );
}

/**
 * The fields a resume parse proposed, each with a checkbox. Nothing reaches the profile from
 * here except by "Copy into the profile form", and even then only after you press Save.
 */
export function ParsedProposal({ parsed, onApply }: { parsed: Parsed; onApply: (selection: ProposalSelection) => void }) {
  const confidence = parsed.field_confidence ?? {};
  const education = educationOf(parsed);
  const projects = projectsOf(parsed);

  const rows: Array<{
    key: Key;
    label: string;
    confidenceKey?: string;
    available: boolean;
    value: ProposalSelection[Key];
    render: React.ReactNode;
  }> = [
    { key: "full_name", label: "Full name", confidenceKey: "full_name", available: Boolean(parsed.full_name), value: parsed.full_name, render: parsed.full_name },
    { key: "email", label: "Email", confidenceKey: "email", available: Boolean(parsed.email), value: parsed.email, render: parsed.email },
    { key: "phone", label: "Phone", confidenceKey: "phone", available: Boolean(parsed.phone), value: parsed.phone, render: parsed.phone },
    { key: "links", label: "Links", confidenceKey: "links", available: Boolean(parsed.links?.length), value: parsed.links ?? [], render: <Chips items={parsed.links ?? []} /> },
    { key: "skills", label: "Skills", confidenceKey: "skills", available: Boolean(parsed.skills?.length), value: parsed.skills ?? [], render: <Chips items={parsed.skills ?? []} /> },
    {
      key: "education",
      label: "Education",
      confidenceKey: "education",
      available: education.length > 0,
      value: education,
      render: (
        <ul className="space-y-0.5 text-xs text-text-2">
          {education.map((entry, index) => (
            <li key={index}>
              {entry.degree || "Degree not stated"}
              {entry.institution ? ` · ${entry.institution}` : ""}
              {entry.start_year || entry.end_year ? ` · ${entry.start_year || "?"}–${entry.end_year || "?"}` : ""}
            </li>
          ))}
        </ul>
      ),
    },
    {
      key: "projects",
      label: "Projects",
      confidenceKey: "projects",
      available: projects.length > 0,
      value: projects,
      render: (
        <ul className="space-y-0.5 text-xs text-text-2">
          {projects.map((entry, index) => (
            <li key={index}>
              <span className="text-text-1">{entry.name || "Untitled"}</span>
              {entry.technologies?.length ? <span className="text-text-3"> · {entry.technologies.join(", ")}</span> : null}
            </li>
          ))}
        </ul>
      ),
    },
    {
      key: "certifications",
      label: "Certifications",
      confidenceKey: "certifications",
      available: Boolean(parsed.certifications?.length),
      value: parsed.certifications ?? [],
      render: <Chips items={parsed.certifications ?? []} />,
    },
    {
      key: "graduation_date",
      label: "Graduation date",
      confidenceKey: "graduation_date",
      available: Boolean(parsed.graduation_date),
      value: parsed.graduation_date ?? "",
      render: parsed.graduation_date,
    },
    {
      key: "years_experience",
      label: "Years of experience",
      confidenceKey: "estimated_years_experience",
      available: parsed.estimated_years_experience !== null && parsed.estimated_years_experience !== undefined,
      value: parsed.estimated_years_experience ?? undefined,
      render:
        parsed.estimated_years_experience !== null && parsed.estimated_years_experience !== undefined
          ? `${parsed.estimated_years_experience} (estimated from dates on the resume)`
          : null,
    },
  ];

  const [picked, setPicked] = useState<Set<Key>>(() => new Set());
  const toggle = (key: Key, on: boolean) =>
    setPicked((current) => {
      const next = new Set(current);
      if (on) next.add(key);
      else next.delete(key);
      return next;
    });

  const apply = () => {
    const selection: ProposalSelection = {};
    for (const row of rows) {
      if (!picked.has(row.key) || !row.available) continue;
      (selection as Record<Key, unknown>)[row.key] = row.value;
    }
    onApply(selection);
    setPicked(new Set());
  };

  const reference = [
    { label: "Experience", items: (parsed.experience ?? []) as Record<string, unknown>[] },
    { label: "Internships", items: (parsed.internships ?? []) as Record<string, unknown>[] },
  ].filter((group) => group.items.length);

  return (
    <div className="space-y-4">
      <ul className="divide-y divide-line rounded-xl border border-line">
        {rows.map((row) => {
          const id = `proposal-${row.key}`;
          return (
            <li key={row.key} className={cn("flex items-start gap-3 px-3 py-2.5", !row.available && "opacity-70")}>
              <Checkbox
                id={id}
                className="mt-0.5"
                checked={picked.has(row.key)}
                disabled={!row.available}
                onCheckedChange={(state) => toggle(row.key, state === true)}
              />
              <div className="min-w-0 flex-1 space-y-1">
                <div className="flex items-center justify-between gap-2">
                  <label htmlFor={id} className="text-xs font-medium text-text-2">
                    {row.label}
                  </label>
                  {row.available ? <Confidence value={row.confidenceKey ? confidence[row.confidenceKey] : undefined} /> : null}
                </div>
                <div className="break-words text-sm text-text-1">
                  {row.available ? row.render : <span className="text-xs text-text-3 italic">not found in the file</span>}
                </div>
              </div>
            </li>
          );
        })}
      </ul>

      {reference.length || parsed.achievements?.length ? (
        <details className="group rounded-xl border border-line px-3 py-2.5">
          <summary className="cursor-pointer text-xs font-medium text-text-2 outline-none hover:text-text-1">
            Also read from the file (reference only)
          </summary>
          <div className="mt-2 space-y-3 text-xs text-text-2">
            <p className="flex gap-1.5 text-text-3">
              <Info className="mt-0.5 size-3.5 shrink-0" /> The profile has no field for these; interview prep and variants read them
              from the resume directly.
            </p>
            {reference.map((group) => (
              <div key={group.label}>
                <p className="mb-1 font-medium text-text-1">{group.label}</p>
                <ul className="space-y-1">
                  {group.items.map((item, index) => (
                    <li key={index} className="leading-relaxed">
                      {s(item.raw) || s(item.title) || "—"}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
            {parsed.achievements?.length ? (
              <div>
                <p className="mb-1 font-medium text-text-1">Achievements</p>
                <ul className="list-disc space-y-1 pl-4">
                  {parsed.achievements.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        </details>
      ) : null}

      <div className="flex flex-col gap-3 rounded-xl bg-surface-2/60 p-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-xs leading-relaxed text-text-3">
          Lists are merged with what you have; single values replace it. You review everything before saving.
        </p>
        <Button type="button" size="sm" onClick={apply} disabled={picked.size === 0} className="shrink-0">
          <ArrowRightToLine /> Copy {picked.size || ""} into the profile form
        </Button>
      </div>
    </div>
  );
}
