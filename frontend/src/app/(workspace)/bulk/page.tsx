import type { Metadata } from "next";
import { Suspense } from "react";

import { BulkView, BulkViewSkeleton } from "@/components/bulk/bulk-view";

export const metadata: Metadata = { title: "Bulk preparation" };

export default function Page() {
  return (
    <Suspense fallback={<BulkViewSkeleton />}>
      <BulkView />
    </Suspense>
  );
}
