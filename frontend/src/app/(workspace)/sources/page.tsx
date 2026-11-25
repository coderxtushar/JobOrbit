import type { Metadata } from "next";

import { SourcesView } from "@/components/sources/sources-view";

export const metadata: Metadata = {
  title: "Sources",
  description: "Job sources, platform permissions, discovery runs, file imports and the capture extension.",
};

export default function SourcesPage() {
  return <SourcesView />;
}
