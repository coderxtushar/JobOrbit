import type { Metadata } from "next";
import { Suspense } from "react";

import { JobsView, JobsViewSkeleton } from "@/components/jobs/jobs-view";

export const metadata: Metadata = { title: "Jobs" };

export default function Page() {
  return (
    <Suspense fallback={<JobsViewSkeleton />}>
      <JobsView />
    </Suspense>
  );
}
