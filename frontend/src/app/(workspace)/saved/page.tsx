import type { Metadata } from "next";
import { Suspense } from "react";

import { JobsViewSkeleton } from "@/components/jobs/jobs-view";
import { SavedView } from "@/components/jobs/saved-view";

export const metadata: Metadata = { title: "Saved jobs" };

export default function Page() {
  return (
    <Suspense fallback={<JobsViewSkeleton />}>
      <SavedView />
    </Suspense>
  );
}
