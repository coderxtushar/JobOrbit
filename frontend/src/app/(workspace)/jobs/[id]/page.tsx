import type { Metadata } from "next";

import { JobPageView } from "@/components/jobs/job-page-view";

export const metadata: Metadata = { title: "Job" };

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <JobPageView id={id} />;
}
