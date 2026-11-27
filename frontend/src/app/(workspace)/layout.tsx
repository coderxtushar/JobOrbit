import { AppShell } from "@/components/layout/app-shell";
import { AUTH_ENABLED } from "@/lib/auth/session";

export default function WorkspaceLayout({ children }: { children: React.ReactNode }) {
  return <AppShell signInAvailable={AUTH_ENABLED}>{children}</AppShell>;
}
