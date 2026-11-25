import type { Metadata } from "next";

import { HomePage } from "@/components/home/home-page";

export const metadata: Metadata = {
  title: { absolute: "JobOrbit · Find the right jobs, let it fill the forms" },
  description:
    "JobOrbit finds openings on company job boards, scores them against your résumé, and fills Greenhouse, Lever and Ashby forms only for the jobs you approve.",
};

export default function Home() {
  return <HomePage />;
}
