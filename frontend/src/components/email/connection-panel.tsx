"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowUpRight,
  CheckCircle2,
  Loader2,
  LogOut,
  Mail,
  MailX,
  PlugZap,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/inbox/confirm-dialog";
import { errorMessage } from "@/components/shared/query-state";
import { StatusBadge } from "@/components/shared/status-badge";
import { Surface } from "@/components/shared/surface";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/endpoints";
import type { Schemas } from "@/lib/api/client";
import { formatDateTime, formatNumber, formatRelative } from "@/lib/formatting";
import { cn } from "@/lib/utils";

type Status = Schemas["EmailTrackingStatus"];
type SyncReport = Schemas["EmailSyncResponse"];

const ENV_SNIPPET = `JA_EMAIL_TRACKING_ENABLED=true
JA_GMAIL_CLIENT_ID=<your OAuth client id>.apps.googleusercontent.com
JA_GMAIL_CLIENT_SECRET=<your OAuth client secret>
# optional
JA_EMAIL_SYNC_DAYS=30
JA_EMAIL_MAX_MESSAGES=200`;

/** Connection state, setup instructions, and the account controls (sync, disconnect, delete). */
export function ConnectionPanel({ status }: { status: Status }) {
  const queryClient = useQueryClient();
  const [authUrl, setAuthUrl] = useState<string | null>(null);
  const [connectError, setConnectError] = useState<string | null>(null);
  const [syncReports, setSyncReports] = useState<SyncReport[] | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<"disconnect" | "delete" | null>(null);

  const refreshAll = () => queryClient.invalidateQueries({ queryKey: ["email"] });

  const connect = useMutation({
    mutationFn: api.gmailConnect,
    onSuccess: (result) => {
      setConnectError(null);
      setAuthUrl(result.auth_url);
      const opened = window.open(result.auth_url, "_blank", "noopener,noreferrer");
      if (!opened) toast.message("Your browser blocked the new tab", { description: "Use the “Open Google sign-in” link." });
    },
    onError: (failure) => setConnectError(errorMessage(failure)),
  });

  const sync = useMutation({
    mutationFn: api.syncEmail,
    onSuccess: (reports) => {
      setSyncError(null);
      setSyncReports(reports);
      const kept = reports.reduce((sum, report) => sum + report.kept, 0);
      toast.success("Sync finished", { description: `${formatNumber(kept)} job-related email${kept === 1 ? "" : "s"} kept.` });
      void refreshAll();
    },
    onError: (failure) => {
      setSyncError(errorMessage(failure));
      void refreshAll();
    },
  });

  const disconnect = useMutation({
    mutationFn: api.disconnectEmail,
    onSuccess: (result) => {
      toast.success("Gmail disconnected", {
        description: `${formatNumber(result.disconnected)} account${result.disconnected === 1 ? "" : "s"} disconnected, ${formatNumber(result.revoked)} token${result.revoked === 1 ? "" : "s"} revoked at Google. Stored emails remain until you delete them.`,
      });
      setConfirm(null);
      setAuthUrl(null);
      void refreshAll();
    },
    onError: (failure) => toast.error("Could not disconnect", { description: errorMessage(failure) }),
  });

  const wipe = useMutation({
    mutationFn: api.deleteEmailData,
    onSuccess: (result) => {
      toast.success("Email data deleted", {
        description: `${formatNumber(result.messages)} emails, ${formatNumber(result.suggestions)} suggestions and ${formatNumber(result.accounts)} account records removed.`,
      });
      setConfirm(null);
      setSyncReports(null);
      setAuthUrl(null);
      void refreshAll();
    },
    onError: (failure) => toast.error("Could not delete email data", { description: errorMessage(failure) }),
  });

  const accounts = status.accounts ?? [];
  const state: "disabled" | "unconfigured" | "ready" | "connected" = !status.enabled
    ? "disabled"
    : !status.oauth_configured
      ? "unconfigured"
      : status.connected
        ? "connected"
        : "ready";

  const headline = {
    disabled: { title: "Email tracking is off", tone: "neutral" as const, icon: MailX },
    unconfigured: { title: "Enabled, but no Google OAuth client is set", tone: "warning" as const, icon: AlertTriangle },
    ready: { title: "Ready to connect Gmail", tone: "violet" as const, icon: PlugZap },
    connected: { title: "Gmail connected", tone: "success" as const, icon: CheckCircle2 },
  }[state];
  const HeadlineIcon = headline.icon;

  return (
    <Surface className="overflow-hidden p-0">
      <div className="grid gap-0 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="space-y-5 p-5 sm:p-6">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div className="flex items-start gap-3">
              <span
                className={cn(
                  "grid size-10 shrink-0 place-items-center rounded-xl ring-1 ring-inset",
                  state === "connected" && "bg-success-soft text-success ring-success/20",
                  state === "ready" && "bg-violet-soft text-violet ring-violet/20 shadow-glow",
                  state === "unconfigured" && "bg-warning-soft text-warning ring-warning/20",
                  state === "disabled" && "bg-surface-3 text-text-2 ring-line-strong",
                )}
              >
                <HeadlineIcon className="size-5" />
              </span>
              <div className="space-y-1">
                <h2 className="font-heading text-base font-semibold text-text-1">{headline.title}</h2>
                <p className="max-w-xl text-sm leading-relaxed text-text-2">
                  {state === "disabled"
                    ? "Nothing is read from any mailbox. You can still paste an email below and it goes through the same classification and matching."
                    : state === "unconfigured"
                      ? "Google requires every app that reads Gmail to use its own OAuth client. Create one in your own Google Cloud project, then restart JobOrbit."
                      : state === "ready"
                        ? "Connecting opens Google's sign-in in a new tab. JobOrbit never sees your password and asks for read-only access only."
                        : "Replies to your applications are read on sync and turned into suggestions you accept or dismiss."}
                </p>
              </div>
            </div>
            <div className="flex shrink-0 flex-wrap gap-2">
              {state === "ready" ? (
                <Button onClick={() => connect.mutate()} disabled={connect.isPending}>
                  {connect.isPending ? <Loader2 className="animate-spin" /> : <Mail />}
                  Connect Gmail
                </Button>
              ) : null}
              {state === "connected" ? (
                <>
                  <Button onClick={() => sync.mutate()} disabled={sync.isPending}>
                    {sync.isPending ? <Loader2 className="animate-spin" /> : <RefreshCw />}
                    Sync now
                  </Button>
                  <Button variant="outline" onClick={() => setConfirm("disconnect")}>
                    <LogOut /> Disconnect
                  </Button>
                </>
              ) : null}
            </div>
          </div>

          {connectError ? (
            <p role="alert" className="rounded-lg border border-danger/25 bg-danger-soft px-3 py-2 text-xs leading-relaxed text-text-1">
              {connectError}
            </p>
          ) : null}

          {authUrl && state !== "connected" ? (
            <div className="flex flex-col gap-3 rounded-lg border border-violet/25 bg-violet-soft p-3 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-xs leading-relaxed text-text-2">
                Finish in the Google tab: choose your account and allow read-only access. Google may warn the app is
                unverified; that is expected for your own testing-mode client. Close the tab when it says “Gmail connected”.
              </p>
              <div className="flex shrink-0 gap-2">
                <Button asChild size="sm" variant="outline">
                  <a href={authUrl} target="_blank" rel="noopener noreferrer">
                    Open Google sign-in <ArrowUpRight />
                  </a>
                </Button>
                <Button size="sm" onClick={() => void refreshAll()}>
                  I have finished
                </Button>
              </div>
            </div>
          ) : null}

          {state === "disabled" || state === "unconfigured" ? (
            <div className="space-y-3">
              <ol className="space-y-2 text-sm text-text-2">
                {[
                  "Create an OAuth client (type Desktop app) in your own Google Cloud project, with the Gmail API enabled and only the gmail.readonly scope.",
                  "Add the settings below to your .env file.",
                  "Restart JobOrbit, come back here and press Connect Gmail.",
                ].map((step, index) => (
                  <li key={step} className="flex gap-3">
                    <span className="grid size-5 shrink-0 place-items-center rounded-full bg-surface-3 text-[11px] font-semibold text-text-1 tabular">
                      {index + 1}
                    </span>
                    <span className="leading-relaxed">{step}</span>
                  </li>
                ))}
              </ol>
              <pre className="overflow-x-auto rounded-lg border border-line bg-surface-2 p-3 font-mono text-[12px] leading-relaxed text-text-1">
                {ENV_SNIPPET}
              </pre>
              <p className="text-xs text-text-3">
                The full walkthrough, including what Google&apos;s consent screen will show, is in{" "}
                <code className="rounded bg-surface-2 px-1 py-0.5 font-mono text-[11px] text-text-2">docs/EMAIL_TRACKING.md</code>.
              </p>
            </div>
          ) : null}

          {accounts.length ? (
            <ul className="space-y-2">
              {accounts.map((account) => (
                <li key={account.id} className="rounded-lg border border-line bg-surface-2/50 p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex min-w-0 items-center gap-2">
                      <Mail className="size-4 shrink-0 text-text-3" />
                      <span className="truncate text-sm font-medium text-text-1">{account.address || "Address not reported"}</span>
                      <span className="text-xs text-text-3">{account.provider}</span>
                    </div>
                    <StatusBadge
                      tone={account.status === "connected" ? "success" : account.status === "reauth_required" ? "warning" : "neutral"}
                    >
                      {account.status.replace(/_/g, " ")}
                    </StatusBadge>
                  </div>
                  <dl className="mt-2 grid gap-x-6 gap-y-1 text-xs sm:grid-cols-3">
                    <div>
                      <dt className="text-text-3">Connected</dt>
                      <dd className="text-text-2" title={formatDateTime(account.connected_at)}>
                        {formatRelative(account.connected_at)}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-text-3">Last sync</dt>
                      <dd className="text-text-2" title={formatDateTime(account.last_sync_at)}>
                        {account.last_sync_at ? formatRelative(account.last_sync_at) : "never"}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-text-3">Scopes granted</dt>
                      <dd className="break-all font-mono text-[11px] text-text-2">
                        {account.scopes.length ? account.scopes.map((scope) => scope.split("/").pop()).join(", ") : "—"}
                      </dd>
                    </div>
                  </dl>
                  {account.last_error ? (
                    <p className="mt-2 text-xs text-warning">Last error: {account.last_error}</p>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : null}

          {syncError ? (
            <p role="alert" className="rounded-lg border border-danger/25 bg-danger-soft px-3 py-2 text-xs leading-relaxed text-text-1">
              Sync failed: {syncError}
            </p>
          ) : null}
          {syncReports ? <SyncSummary reports={syncReports} /> : null}
        </div>

        <aside className="space-y-4 border-t border-line bg-surface-2/40 p-5 sm:p-6 lg:border-t-0 lg:border-l">
          <p className="text-[11px] font-semibold tracking-[0.12em] text-text-3 uppercase">Configuration</p>
          <dl className="space-y-3 text-xs">
            <Fact label="Tracking enabled" value={status.enabled ? "Yes" : "No"} />
            <Fact label="OAuth client" value={status.oauth_configured ? "Configured" : "Not configured"} />
            <Fact label="Scope requested" value={<code className="font-mono text-[11px]">{status.scope.split("/").pop()}</code>} hint="Read-only. Cannot send, delete, label or modify anything." />
            <Fact label="Looks back" value={`${formatNumber(status.sync_days)} days`} />
            <Fact label="Reads at most" value={`${formatNumber(status.max_messages)} messages per sync`} />
            <Fact label="Token stored in" value={status.secret_backend} hint="Never in the database or a log." />
            <Fact label="Redirect URI" value={<span className="break-all font-mono text-[11px]">{status.redirect_uri}</span>} />
          </dl>
          <div className="border-t border-line pt-4">
            <Button
              variant="ghost"
              size="sm"
              className="w-full justify-start text-danger hover:text-danger"
              onClick={() => setConfirm("delete")}
            >
              <Trash2 /> Delete all email data
            </Button>
          </div>
        </aside>
      </div>

      <ConfirmDialog
        open={confirm === "disconnect"}
        onOpenChange={(open) => (!open ? setConfirm(null) : undefined)}
        title="Disconnect Gmail?"
        description="The token is revoked at Google and removed from your secret store. Emails already stored stay until you delete them."
        confirmLabel="Disconnect"
        pending={disconnect.isPending}
        onConfirm={() => disconnect.mutate()}
      />
      <ConfirmDialog
        open={confirm === "delete"}
        onOpenChange={(open) => (!open ? setConfirm(null) : undefined)}
        title="Delete all email data?"
        description="This disconnects any account, then deletes every stored email, every suggestion made from one, and the account records. It cannot be undone. Changes you already accepted stay on your applications: they are your decisions, not email data."
        confirmLabel="Delete everything"
        pending={wipe.isPending}
        onConfirm={() => wipe.mutate()}
      />
    </Surface>
  );
}

function Fact({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="space-y-0.5">
      <dt className="text-text-3">{label}</dt>
      <dd className="text-text-1">{value}</dd>
      {hint ? <dd className="text-[11px] text-text-3">{hint}</dd> : null}
    </div>
  );
}

function SyncSummary({ reports }: { reports: SyncReport[] }) {
  return (
    <div className="space-y-2" aria-live="polite">
      {reports.map((report) => (
        <div key={report.account_id} className="rounded-lg border border-line bg-surface-2/50 p-3">
          <p className="mb-2 text-xs font-medium text-text-1">Last sync · account #{report.account_id}</p>
          <dl className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
            {(
              [
                ["Listed", report.listed],
                ["Read", report.fetched],
                ["Kept", report.kept],
                ["Duplicates", report.duplicates],
                ["Not job-related", report.skipped_not_job_related],
                ["Suggestions", report.suggestions],
                ["Need your pick", report.needs_review],
              ] as const
            ).map(([label, value]) => (
              <div key={label}>
                <dt className="text-text-3">{label}</dt>
                <dd className="font-heading text-sm font-semibold text-text-1 tabular">{formatNumber(value)}</dd>
              </div>
            ))}
          </dl>
          {report.errors.length ? (
            <ul className="mt-2 space-y-1 text-xs text-warning">
              {report.errors.map((error) => (
                <li key={error}>{error}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ))}
    </div>
  );
}
