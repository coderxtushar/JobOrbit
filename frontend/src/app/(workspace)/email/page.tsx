import type { Metadata } from "next";

import { EmailView } from "@/components/email/email-view";

export const metadata: Metadata = {
  title: "Email tracking",
  description: "Read-only Gmail tracking of replies to your applications, as suggestions you accept.",
};

export default function Page() {
  return <EmailView />;
}
