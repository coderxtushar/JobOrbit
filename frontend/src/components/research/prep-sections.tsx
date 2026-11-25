"use client";

import {
  Brain,
  Building2,
  Code2,
  FileUser,
  FolderGit2,
  MessagesSquare,
  Mic,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";

import { StatusBadge } from "@/components/shared/status-badge";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Button } from "@/components/ui/button";

import { PREP_SECTIONS, type PrepContent, type PrepItem } from "./research-types";
import { SourceCitation } from "./source-citation";

const SECTION_ICON: Record<string, LucideIcon> = {
  technical: Brain,
  resume: FileUser,
  projects: FolderGit2,
  behavioural: MessagesSquare,
  coding: Code2,
  company: Building2,
  skill_gaps: TriangleAlert,
};

function ItemRow({
  item,
  practisable,
  practisedCount,
  onPractise,
}: {
  item: PrepItem;
  practisable: boolean;
  practisedCount: number;
  onPractise: (item: PrepItem) => void;
}) {
  return (
    <li className="group flex flex-col gap-2 rounded-lg border border-transparent px-3 py-2.5 transition-colors hover:border-line hover:bg-surface-2/50 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0 space-y-1">
        <p className="text-[13.5px] leading-relaxed text-text-1">{item.question}</p>
        <p className="text-[11.5px] leading-snug text-text-3">
          <span className="text-text-2">Derived from</span> {item.derived_from}
        </p>
        <div className="flex flex-wrap items-center gap-1.5">
          {item.skill ? (
            <span className="rounded bg-surface-3 px-1.5 py-px text-[10.5px] text-text-2">{item.skill}</span>
          ) : null}
          {item.level ? (
            <span className="rounded bg-warning-soft px-1.5 py-px text-[10.5px] text-warning">{item.level}</span>
          ) : null}
          {item.project ? (
            <span className="rounded bg-cyan-soft px-1.5 py-px text-[10.5px] text-cyan">{item.project}</span>
          ) : null}
          {item.source ? <SourceCitation source={item.source} /> : null}
          {practisedCount ? (
            <span className="text-[10.5px] text-text-3">
              practised {practisedCount}×
            </span>
          ) : null}
        </div>
      </div>
      {practisable ? (
        <Button
          size="xs"
          variant="ghost"
          className="shrink-0 self-start text-text-3 group-hover:text-violet focus-visible:text-violet"
          onClick={() => onPractise(item)}
        >
          <Mic /> Practise
        </Button>
      ) : null}
    </li>
  );
}

/** All seven sections, each item naming what it was derived from. */
export function PrepSections({
  content,
  practiceCounts,
  onPractise,
}: {
  content: PrepContent;
  practiceCounts: Map<string, number>;
  onPractise: (item: PrepItem) => void;
}) {
  const sections = content.sections ?? {};
  const present = PREP_SECTIONS.map((section) => ({ ...section, items: sections[section.key] ?? [] }));

  return (
    <Accordion
      type="multiple"
      defaultValue={present.filter((section) => section.items.length).slice(0, 2).map((section) => section.key)}
      className="orbit-card overflow-hidden"
    >
      {present.map((section) => {
        const Icon = SECTION_ICON[section.key] ?? Brain;
        return (
          <AccordionItem key={section.key} value={section.key} className="border-line">
            <AccordionTrigger className="px-4 py-3.5 hover:no-underline sm:px-5">
              <span className="flex min-w-0 flex-1 items-center gap-3">
                <span className="grid size-7 shrink-0 place-items-center rounded-lg bg-violet-soft text-violet ring-1 ring-inset ring-violet/20">
                  <Icon className="size-3.5" />
                </span>
                <span className="min-w-0 text-left">
                  <span className="flex items-center gap-2">
                    <span className="font-heading text-sm font-semibold text-text-1">{section.label}</span>
                    <span className="tabular rounded-full bg-surface-3 px-1.5 text-[10.5px] text-text-2">
                      {section.items.length}
                    </span>
                    {section.key === "skill_gaps" && section.items.length ? (
                      <StatusBadge tone="warning" dot={false} className="hidden sm:inline-flex">
                        prepare, don&apos;t claim
                      </StatusBadge>
                    ) : null}
                  </span>
                  <span className="block truncate text-xs font-normal text-text-3">{section.hint}</span>
                </span>
              </span>
            </AccordionTrigger>
            <AccordionContent className="px-2 pb-3 sm:px-3">
              {section.items.length ? (
                <ul className="space-y-0.5">
                  {section.items.map((item) => (
                    <ItemRow
                      key={item.id}
                      item={item}
                      practisable={section.practisable}
                      practisedCount={practiceCounts.get(item.id) ?? 0}
                      onPractise={onPractise}
                    />
                  ))}
                </ul>
              ) : (
                <p className="px-3 py-2 text-xs text-text-3 italic">
                  {section.key === "skill_gaps"
                    ? "No gaps: every skill this listing names is already in your profile."
                    : section.key === "projects"
                      ? "No projects are recorded in your profile, so there are no project questions."
                      : "Nothing in the listing or your profile supports items here."}
                </p>
              )}
            </AccordionContent>
          </AccordionItem>
        );
      })}
    </Accordion>
  );
}
