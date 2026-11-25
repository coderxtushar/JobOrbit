import type { Metadata } from "next";

import { AnalyticsView } from "@/components/analytics/analytics-view";

export const metadata: Metadata = {
  title: "Analytics",
  description: "Submission funnel, conversion rates, segments and data quality from recorded data.",
};

export default function AnalyticsPage() {
  return <AnalyticsView />;
}
