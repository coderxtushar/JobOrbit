import type { Metadata } from "next";

import { SettingsView } from "@/components/settings/settings-view";

export const metadata: Metadata = {
  title: "Settings",
  description: "Appearance, installation facts, auto-apply safety and the .env reference.",
};

export default function SettingsPage() {
  return <SettingsView />;
}
