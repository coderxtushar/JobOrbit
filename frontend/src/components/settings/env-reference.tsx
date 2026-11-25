"use client";

import { Copy, FileCode2, RotateCcw } from "lucide-react";
import { toast } from "sonner";

import { SectionHeading } from "@/components/shared/page-header";
import { Surface } from "@/components/shared/surface";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";

interface EnvKey {
  key: string;
  fallback: string;
  about: string;
}

interface EnvGroup {
  id: string;
  title: string;
  summary: string;
  keys: EnvKey[];
}

/** The important keys from .env.example, with its defaults and its own explanations. */
const GROUPS: EnvGroup[] = [
  {
    id: "server",
    title: "Server and privacy",
    summary: "Where the API listens and who can reach it.",
    keys: [
      { key: "JA_API_HOST", fallback: "127.0.0.1", about: "Bind to loopback only. Changing this exposes your resume data on the network." },
      { key: "JA_API_PORT", fallback: "8000", about: "Port the API listens on." },
      { key: "JA_API_TOKEN", fallback: "(empty)", about: "Required when the host is not a loopback address. Also needed by the capture extension." },
      { key: "JA_DISPLAY_TIMEZONE", fallback: "Asia/Kolkata", about: "Timezone for display. Everything is stored in UTC." },
      { key: "JA_DEMO_MODE", fallback: "false", about: "Public-demo deployment with fictional data; refuses uploads and source changes." },
      { key: "JA_LOG_LEVEL", fallback: "INFO", about: "API log verbosity." },
    ],
  },
  {
    id: "storage",
    title: "Storage",
    summary: "Database and private data folder.",
    keys: [
      { key: "JA_DATABASE_URL", fallback: "sqlite+pysqlite:///./var/jobassist.db", about: "SQLAlchemy URL. PostgreSQL works unchanged." },
      { key: "JA_DATA_DIR", fallback: "./var", about: "Private data directory, never served statically." },
      { key: "JA_MAX_UPLOAD_MB", fallback: "10", about: "Largest resume upload accepted." },
    ],
  },
  {
    id: "llm",
    title: "Language model (optional)",
    summary: "Leave off for deterministic, rule-based drafting.",
    keys: [
      { key: "JA_LLM_PROVIDER", fallback: "none", about: "none | openai | openai_compatible." },
      { key: "JA_LLM_MODEL", fallback: "gpt-4o-mini", about: "Model name sent to the provider." },
      { key: "JA_LLM_API_KEY", fallback: "(empty)", about: "Provider key. Read from the environment; never shown here." },
      { key: "JA_LLM_BASE_URL", fallback: "(empty)", about: "For OpenAI-compatible servers, including local ones." },
    ],
  },
  {
    id: "discovery",
    title: "Discovery and scheduling",
    summary: "Company boards, open feeds and the background scheduler.",
    keys: [
      { key: "JA_SCHEDULER_ENABLED", fallback: "false", about: "Off by default: no background activity unless enabled." },
      { key: "JA_DISCOVERY_INTERVAL_MINUTES", fallback: "360", about: "How often the scheduler runs discovery." },
      { key: "JA_ATS_DISCOVERY_ENABLED", fallback: "true", about: "Master switch for per-company ATS boards." },
      {
        key: "JA_GREENHOUSE_BOARDS",
        fallback: "(empty)",
        about: "Comma-separated board slugs. Likewise JA_LEVER_BOARDS, JA_WORKABLE_BOARDS, JA_ASHBY_BOARDS, JA_SMARTRECRUITERS_BOARDS. Nothing is fetched until you name companies.",
      },
      { key: "JA_FEED_DISCOVERY_ENABLED", fallback: "false", about: "Master switch for whole-feed APIs. Each feed also needs its own switch." },
      {
        key: "JA_REMOTEOK_ENABLED",
        fallback: "false",
        about: "Per-feed switch. Likewise JA_ARBEITNOW_ENABLED, JA_REMOTIVE_ENABLED, JA_HIMALAYAS_ENABLED, JA_JOBICY_ENABLED.",
      },
      { key: "JA_EMAIL_INGEST_ENABLED", fallback: "false", about: "Read job-alert emails over IMAP (with JA_EMAIL_IMAP_HOST, JA_EMAIL_USERNAME, JA_EMAIL_APP_PASSWORD)." },
    ],
  },
  {
    id: "autoapply",
    title: "Auto-apply and evidence",
    summary: "Browser submission on supported hosted forms, and its limits.",
    keys: [
      { key: "JA_BROWSER_SUBMISSION_ENABLED", fallback: "false", about: "When true, live runs fill and submit Greenhouse, Lever and Ashby forms. LinkedIn, Naukri, Indeed and Wellfound are never applied to." },
      { key: "JA_BROWSER_DAILY_SUBMISSION_CAP", fallback: "25", about: "Most submissions in one day." },
      { key: "JA_BROWSER_HEADLESS", fallback: "false", about: "Run the browser without a window." },
      { key: "JA_BROWSER_MAX_CONCURRENT_PER_PLATFORM", fallback: "1", about: "Parallel submissions per platform." },
      { key: "JA_CIRCUIT_BREAKER_THRESHOLD", fallback: "3", about: "Consecutive failures that pause a platform." },
      { key: "JA_EVIDENCE_RETENTION_DAYS", fallback: "30", about: "Days screenshots and event logs are kept." },
      { key: "JA_EVIDENCE_SCREENSHOTS", fallback: "true", about: "Screenshot the confirmation or failure page of every browser attempt." },
    ],
  },
  {
    id: "email",
    title: "Email response tracking",
    summary: "Read-only Gmail access to match replies to applications.",
    keys: [
      { key: "JA_EMAIL_TRACKING_ENABLED", fallback: "false", about: "Opt-in. Tokens go to the OS keychain, never .env." },
      { key: "JA_GMAIL_CLIENT_ID", fallback: "(empty)", about: "Desktop-app OAuth client from your own Google Cloud project (with JA_GMAIL_CLIENT_SECRET)." },
      { key: "JA_EMAIL_SYNC_DAYS", fallback: "30", about: "How far back a sync reads." },
    ],
  },
  {
    id: "analytics",
    title: "Analytics, research and bulk",
    summary: "Assumptions behind estimates, and batch limits.",
    keys: [
      { key: "JA_MINUTES_PER_MANUAL_APPLICATION", fallback: "12", about: "The assumption behind the “time saved” estimate on Analytics." },
      { key: "JA_USD_INR_RATE", fallback: "(unset)", about: "Show USD salaries in INR at a rate you choose. Never guessed otherwise." },
      { key: "JA_COMPANY_RESEARCH_EXTERNAL", fallback: "false", about: "Allow fetching a company’s own website (title and description) when you ask for research." },
      { key: "JA_BATCH_CONCURRENCY", fallback: "4", about: "Parallel work in bulk preparation." },
      { key: "JA_BATCH_MAX_JOBS", fallback: "500", about: "Largest bulk preparation run." },
    ],
  },
];

async function copy(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    toast.success(`Copied ${text}`);
  } catch {
    toast.error("Could not copy to the clipboard");
  }
}

/**
 * The API has no settings-write endpoint, so configuration lives in .env. This lists the
 * keys that matter with their defaults; it does not pretend to edit them.
 */
export function EnvReference({ live }: { live: Record<string, string | undefined> }) {
  return (
    <Surface className="p-5">
      <SectionHeading
        title="Configuration file"
        description="Everything else is set in .env at the repository root. Every key has a safe default; the app runs with no .env at all."
      />
      <div className="mb-4 grid gap-2 sm:grid-cols-3">
        {[
          { icon: FileCode2, text: "Copy .env.example to .env and edit it. Never commit .env." },
          { icon: RotateCcw, text: "Restart the API after a change; it reads .env once at start-up." },
          { icon: Copy, text: "Secrets (API keys, passwords) are read from the environment and never shown here." },
        ].map((tip) => (
          <div key={tip.text} className="flex items-start gap-2.5 rounded-lg bg-surface-2/50 p-3 text-xs leading-relaxed text-text-2">
            <tip.icon className="mt-0.5 size-3.5 shrink-0 text-violet" />
            {tip.text}
          </div>
        ))}
      </div>
      <Accordion type="multiple" defaultValue={["autoapply"]} className="rounded-lg border border-line">
        {GROUPS.map((group) => (
          <AccordionItem key={group.id} value={group.id} className="border-line px-4">
            <AccordionTrigger className="py-3 hover:no-underline">
              <span>
                <span className="block text-sm font-medium text-text-1">{group.title}</span>
                <span className="block text-xs font-normal text-text-3">{group.summary}</span>
              </span>
            </AccordionTrigger>
            <AccordionContent>
              <ul className="divide-y divide-line pb-3">
                {group.keys.map((item) => (
                  <li key={item.key} className="grid gap-1 py-2.5 md:grid-cols-[minmax(0,17rem)_1fr] md:gap-4">
                    <div className="min-w-0">
                      <button
                        type="button"
                        onClick={() => copy(item.key)}
                        className="group inline-flex max-w-full items-center gap-1.5 rounded font-mono text-[12px] text-text-1 outline-none hover:text-violet focus-visible:ring-2 focus-visible:ring-ring"
                        title="Copy key"
                      >
                        <span className="truncate">{item.key}</span>
                        <Copy className="size-3 shrink-0 opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100" />
                      </button>
                      <p className="mt-0.5 text-[11px] text-text-3">
                        default <span className="font-mono">{item.fallback}</span>
                        {live[item.key] !== undefined ? (
                          <>
                            {" · "}
                            <span className="text-cyan">running: {live[item.key]}</span>
                          </>
                        ) : null}
                      </p>
                    </div>
                    <p className="text-xs leading-relaxed text-text-2">{item.about}</p>
                  </li>
                ))}
              </ul>
            </AccordionContent>
          </AccordionItem>
        ))}
      </Accordion>
    </Surface>
  );
}
