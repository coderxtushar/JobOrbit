"use client";

import { BookmarkPlus, Info } from "lucide-react";
import Link from "next/link";

import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";

import { JobBrowser } from "./job-browser";

/** /saved: jobs with status SHORTLISTED, with the same cards, panel and bulk actions. */
export function SavedView() {
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Shortlist"
        title="Saved jobs"
        description="Jobs you saved from discovery. Prepare them one by one, in bulk, or hand them to the auto-apply preflight."
        actions={
          <Button variant="outline" asChild>
            <Link href="/jobs">
              <BookmarkPlus /> Find more jobs
            </Link>
          </Button>
        }
      />
      <div className="flex items-start gap-2.5 rounded-xl border border-line bg-surface-1/70 px-3.5 py-2.5 text-xs leading-relaxed text-text-2">
        <Info className="mt-0.5 size-3.5 shrink-0 text-cyan" aria-hidden />
        <p>
          The JobOrbit API has no &ldquo;unsave&rdquo;. To take a job off this list, open it and choose{" "}
          <span className="font-medium text-text-1">Skip</span>: it is marked skipped and left out of bulk
          preparation.
        </p>
      </div>
      <JobBrowser
        fixedStatus="SHORTLISTED"
        emptyState={
          <EmptyState
            icon={BookmarkPlus}
            title="Nothing saved yet"
            description="Save jobs from the Jobs page with the bookmark on a card or in the detail panel."
            action={
              <Button size="sm" asChild>
                <Link href="/jobs">Browse jobs</Link>
              </Button>
            }
          />
        }
      />
    </div>
  );
}
