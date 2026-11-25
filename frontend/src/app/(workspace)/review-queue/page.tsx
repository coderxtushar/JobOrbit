import type { Metadata } from "next";

import { ReviewQueueView } from "@/components/applications/review-queue-view";

export const metadata: Metadata = {
  title: "Review queue",
  description: "Prepared applications waiting for your review and approval.",
};

export default function Page() {
  return <ReviewQueueView />;
}
