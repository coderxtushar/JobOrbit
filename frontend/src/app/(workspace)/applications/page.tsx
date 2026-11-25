import type { Metadata } from "next";
import { Suspense } from "react";

import { ApplicationsView } from "@/components/applications/applications-view";
import { Skeleton } from "@/components/ui/skeleton";

export const metadata: Metadata = {
  title: "Applications",
  description: "Your application pipeline, from review to outcome.",
};

export default function Page() {
  return (
    <Suspense
      fallback={
        <div className="space-y-6">
          <div className="space-y-2">
            <Skeleton className="h-3 w-20" />
            <Skeleton className="h-8 w-56" />
            <Skeleton className="h-4 w-96 max-w-full" />
          </div>
          <Skeleton className="h-8 w-full" />
          <div className="flex gap-3 overflow-hidden">
            {Array.from({ length: 5 }).map((_, index) => (
              <Skeleton key={index} className="h-80 w-72 shrink-0 rounded-xl" />
            ))}
          </div>
        </div>
      }
    >
      <ApplicationsView />
    </Suspense>
  );
}
