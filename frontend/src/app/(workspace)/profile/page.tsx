import type { Metadata } from "next";

import { ProfileView } from "@/components/profile/profile-view";

export const metadata: Metadata = {
  title: "Resume and profile",
  description: "Your resumes, their extracted fields and variants, and the profile every application is built from.",
};

export default function Page() {
  return <ProfileView />;
}
