import type { Metadata } from "next";
import { Suspense } from "react";

import { CompanyResearchFallback, CompanyResearchView } from "@/components/research/company-research-view";

export const metadata: Metadata = {
  title: "Company research",
  description: "Cited company profiles built from the listings JobOrbit holds, plus a salary reader.",
};

export default function Page() {
  return (
    <Suspense fallback={<CompanyResearchFallback />}>
      <CompanyResearchView />
    </Suspense>
  );
}
