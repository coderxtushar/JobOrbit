"use client";

import { useQuery } from "@tanstack/react-query";
import { ClipboardPaste, Database, EyeOff, Hand, Inbox, Lightbulb, ShieldCheck } from "lucide-react";

import { PageHeader, SectionHeading } from "@/components/shared/page-header";
import { ErrorState } from "@/components/shared/query-state";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useHealth } from "@/hooks/use-health";
import { api } from "@/lib/api/endpoints";
import { formatNumber } from "@/lib/formatting";

import { ConnectionPanel } from "./connection-panel";
import { IngestPanel } from "./ingest-panel";
import { ReviewInbox } from "./review-inbox";
import { SuggestionsList } from "./suggestions-list";

const GUARANTEES = [
  {
    icon: ShieldCheck,
    title: "Read-only access",
    body: "Only the gmail.readonly scope. JobOrbit cannot send, delete, archive or label anything.",
  },
  {
    icon: Hand,
    title: "Nothing applied automatically",
    body: "Each email becomes a suggestion. An application changes only when you press Accept.",
  },
  {
    icon: Database,
    title: "Kept local and minimal",
    body: "A redacted snippet and extracted facts, in your own database. Never the full body or attachments.",
  },
  {
    icon: EyeOff,
    title: "Not your whole mailbox",
    body: "One narrow search for job-related replies within the sync window. Everything else is skipped.",
  },
];

/** The public demo has no mailbox to read: say so instead of showing refused requests. */
function EmailDemoNotice() {
  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Responses"
        title="Email tracking"
        description="Read replies to your applications from your own Gmail, or paste one in. Each is classified, matched to an application and turned into a suggestion that you decide on."
      />
      <div className="orbit-card flex flex-col items-start gap-3 p-6">
        <span className="grid size-10 place-items-center rounded-xl bg-violet-soft text-violet ring-1 ring-inset ring-violet/20">
          <ShieldCheck className="size-5" />
        </span>
        <p className="text-base font-medium text-text-1">Not available in the public demo</p>
        <p className="max-w-2xl text-sm leading-relaxed text-text-2">
          Email tracking reads a personal mailbox, read-only. A shared demo has no sign-in, so connecting one here would
          expose it to every visitor. Run JobOrbit on your own machine to connect your Gmail; replies then arrive as
          status suggestions you accept or dismiss.
        </p>
      </div>
    </div>
  );
}

export function EmailView() {
  const health = useHealth();
  const demo = health.data?.demo_mode;
  // Until the API says whether this is the demo, render nothing that would call Gmail
  // endpoints; if the API cannot be reached, the live view shows its own error states.
  const live = demo === false || health.isError;
  const status = useQuery({ queryKey: ["email", "status"], queryFn: api.emailStatus, enabled: live });
  const suggestions = useQuery({
    queryKey: ["email", "suggestions", "pending"],
    queryFn: () => api.suggestions("pending", 100),
    enabled: live,
  });
  const review = useQuery({
    queryKey: ["email", "messages", "needs_review"],
    queryFn: () => api.emailMessages({ match_state: "needs_review", limit: 100 }),
    enabled: live,
  });

  if (demo) return <EmailDemoNotice />;
  if (!live) return <Skeleton className="h-96 w-full rounded-xl" />;

  const pendingCount = suggestions.data?.length ?? status.data?.pending_suggestions;
  const reviewCount = review.data?.total ?? status.data?.needs_review;

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Responses"
        title="Email tracking"
        description="Read replies to your applications from your own Gmail, or paste one in. Each is classified, matched to an application and turned into a suggestion that you decide on."
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {GUARANTEES.map(({ icon: Icon, title, body }) => (
          <div key={title} className="flex gap-3 rounded-xl border border-line bg-surface-1/60 p-4">
            <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-violet-soft text-violet ring-1 ring-inset ring-violet/20">
              <Icon className="size-4" />
            </span>
            <div className="space-y-1">
              <p className="text-sm font-medium text-text-1">{title}</p>
              <p className="text-xs leading-relaxed text-text-3">{body}</p>
            </div>
          </div>
        ))}
      </div>

      <section aria-label="Connection">
        {status.isLoading ? (
          <Skeleton className="h-72 w-full rounded-xl" />
        ) : status.isError ? (
          <ErrorState error={status.error} onRetry={() => status.refetch()} />
        ) : status.data ? (
          <ConnectionPanel status={status.data} />
        ) : null}
      </section>

      <Tabs defaultValue="suggestions" className="gap-5">
        <TabsList className="w-full sm:w-fit">
          <TabsTrigger value="suggestions" className="px-3">
            <Lightbulb /> Suggestions
            <Count value={pendingCount} tone="violet" />
          </TabsTrigger>
          <TabsTrigger value="review" className="px-3">
            <Inbox /> Needs your pick
            <Count value={reviewCount} tone="warning" />
          </TabsTrigger>
          <TabsTrigger value="paste" className="px-3">
            <ClipboardPaste /> Paste an email
          </TabsTrigger>
        </TabsList>

        <TabsContent value="suggestions">
          <SectionHeading
            title="Pending suggestions"
            description="Accepting goes through the same transition rules as editing an application by hand. A change that is not allowed is refused with the reason and stays pending."
          />
          <SuggestionsList />
        </TabsContent>
        <TabsContent value="review">
          <SectionHeading
            title="Needs your pick"
            description="Emails linked to no application because more than one was a plausible match."
          />
          <ReviewInbox />
        </TabsContent>
        <TabsContent value="paste">
          <IngestPanel />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function Count({ value, tone }: { value: number | undefined; tone: "violet" | "warning" }) {
  if (value === undefined || value === 0) return null;
  return (
    <span
      className={
        tone === "violet"
          ? "ml-1 rounded-full bg-violet-soft px-1.5 text-[11px] text-violet tabular"
          : "ml-1 rounded-full bg-warning-soft px-1.5 text-[11px] text-warning tabular"
      }
    >
      {formatNumber(value)}
    </span>
  );
}
