import type { Metadata } from "next";

import { ActionInboxView } from "@/components/inbox/action-inbox-view";

export const metadata: Metadata = {
  title: "Action inbox",
  description: "Questions only you can answer, and your bank of reusable answers.",
};

export default function Page() {
  return <ActionInboxView />;
}
