import type { Metadata } from "next";
import { Suspense } from "react";

import { AutoApplyView } from "@/components/auto-apply/auto-apply-view";
import { Skeleton } from "@/components/ui/skeleton";

export const metadata: Metadata = {
  title: "Auto-apply",
  description: "Scope, preflight, approve and run auto-apply, with the emergency stop always in reach.",
};

export default function Page() {
  return (
    <Suspense fallback={<AutoApplySkeleton />}>
      <AutoApplyView />
    </Suspense>
  );
}

function AutoApplySkeleton() {
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <Skeleton className="h-3 w-20" />
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-4 w-96 max-w-full" />
      </div>
      <Skeleton className="h-[92px] w-full rounded-xl" />
      <Skeleton className="h-14 w-full rounded-xl" />
      <Skeleton className="h-[540px] w-full rounded-xl" />
    </div>
  );
}
