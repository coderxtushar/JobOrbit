"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";

import { EmptyState } from "@/components/shared/empty-state";
import { Button } from "@/components/ui/button";

import { JobDetailView } from "./job-detail";

/** /jobs/[id]: the full-screen job view. */
export function JobPageView({ id }: { id: string }) {
  const jobId = Number(id);
  const valid = Number.isInteger(jobId) && jobId > 0;
  return (
    <div className="space-y-5">
      <Button variant="ghost" size="sm" asChild className="-ml-2 text-text-2">
        <Link href="/jobs">
          <ArrowLeft /> All jobs
        </Link>
      </Button>
      {valid ? (
        <JobDetailView jobId={jobId} variant="page" />
      ) : (
        <EmptyState title="Not a job id" description={`"${id}" is not a valid job id.`} />
      )}
    </div>
  );
}
