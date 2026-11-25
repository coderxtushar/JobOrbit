"use client";

import { useQuery } from "@tanstack/react-query";

import { PageHeader } from "@/components/shared/page-header";
import { useHealth } from "@/hooks/use-health";
import { api } from "@/lib/api/endpoints";

import { AppearanceSettings } from "./appearance-settings";
import { EnvReference } from "./env-reference";
import { InstallationFacts } from "./installation-facts";
import { SafetySettings } from "./safety-settings";

/**
 * Settings that genuinely persist: theme and sidebar (this browser) and the one evidence
 * action the API exposes. Everything else is read-only, because the backend has no
 * settings-write endpoint and its configuration lives in .env.
 */
export function SettingsView() {
  const health = useHealth();
  const control = useQuery({ queryKey: ["autoapply", "control"], queryFn: api.control });
  const diagnostics = useQuery({ queryKey: ["logs", "diagnostics"], queryFn: api.diagnostics });

  const h = health.data;
  const c = control.data;
  const live: Record<string, string | undefined> = {
    JA_LLM_PROVIDER: h?.llm_provider,
    JA_SCHEDULER_ENABLED: h ? String(h.scheduler_enabled) : undefined,
    JA_DEMO_MODE: h?.demo_mode === undefined ? undefined : String(h.demo_mode),
    JA_API_HOST: h ? (h.loopback_only ? "loopback" : "non-loopback") : undefined,
    JA_DISPLAY_TIMEZONE: diagnostics.data?.display_timezone,
    JA_BROWSER_SUBMISSION_ENABLED: c ? String(c.browser_submission_enabled) : undefined,
    JA_EVIDENCE_RETENTION_DAYS: c ? String(c.evidence_retention_days) : undefined,
    JA_BROWSER_DAILY_SUBMISSION_CAP:
      c?.browser_submission_enabled && c.daily_cap !== null && c.daily_cap !== undefined ? String(c.daily_cap) : undefined,
  };

  return (
    <div className="space-y-[var(--space-section)]">
      <PageHeader
        eyebrow="Workspace"
        title="Settings"
        description="Appearance is saved in this browser. Installation and safety settings are read from the running API and changed in .env."
      />
      <div className="grid gap-4 xl:grid-cols-2">
        <AppearanceSettings />
        <InstallationFacts health={health} diagnostics={diagnostics.data} />
      </div>
      <SafetySettings control={control} />
      <EnvReference live={live} />
    </div>
  );
}
