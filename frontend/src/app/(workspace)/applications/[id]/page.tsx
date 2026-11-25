import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { ApplicationDetailView } from "@/components/applications/application-detail-view";

export const metadata: Metadata = {
  title: "Application",
  description: "One application: its drafts, answers, versions, status and outcome.",
};

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const applicationId = Number(id);
  if (!Number.isInteger(applicationId) || applicationId <= 0) notFound();
  return <ApplicationDetailView id={applicationId} />;
}
