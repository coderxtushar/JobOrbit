import type { Metadata } from "next";
import { Suspense } from "react";

import { InterviewPrepFallback, InterviewPrepView } from "@/components/research/interview-prep-view";

export const metadata: Metadata = {
  title: "Interview prep",
  description: "Rule-based interview preparation, mock-interview practice and your own interview records.",
};

export default function Page() {
  return (
    <Suspense fallback={<InterviewPrepFallback />}>
      <InterviewPrepView />
    </Suspense>
  );
}
