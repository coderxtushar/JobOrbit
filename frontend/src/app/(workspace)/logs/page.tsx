import type { Metadata } from "next";
import { Suspense } from "react";

import { LogsSkeleton, LogsView } from "@/components/logs/logs-view";

export const metadata: Metadata = {
  title: "Logs and diagnostics",
  description: "API health, per-source diagnostics, the audit log and the duplicate report.",
};

export default function LogsPage() {
  return (
    <Suspense fallback={<LogsSkeleton />}>
      <LogsView />
    </Suspense>
  );
}
