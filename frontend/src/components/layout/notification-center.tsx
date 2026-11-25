"use client";

import { useQuery } from "@tanstack/react-query";
import { Bell, CircleAlert, Inbox, Mail, Octagon, ShieldAlert } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useNavCounts } from "@/hooks/use-nav-counts";
import { useDemoMode } from "@/hooks/use-demo-mode";
import { api } from "@/lib/api/endpoints";

interface Notice {
  key: string;
  icon: typeof Bell;
  title: string;
  detail: string;
  href: string;
  tone: string;
}

/** Things that need the user, each derived from live data. Empty means nothing is waiting. */
export function NotificationCenter() {
  const counts = useNavCounts();
  const demo = useDemoMode();
  const control = useQuery({ queryKey: ["autoapply", "control"], queryFn: api.control, refetchInterval: 30_000 });
  const suggestions = useQuery({
    queryKey: ["email", "suggestions", "pending"],
    queryFn: () => api.suggestions("pending", 100),
    refetchInterval: 120_000,
    retry: false,
    // Gmail tracking is refused in the public demo; ask only once the API says it is not one.
    enabled: demo === false,
  });

  const notices: Notice[] = [];
  if (control.data?.emergency_stop) {
    notices.push({
      key: "stop",
      icon: Octagon,
      title: "Emergency stop is on",
      detail: "No run will start until you clear it.",
      href: "/auto-apply",
      tone: "text-danger",
    });
  }
  for (const breaker of control.data?.breakers ?? []) {
    if (breaker.open) {
      notices.push({
        key: `breaker-${breaker.target}`,
        icon: ShieldAlert,
        title: `${breaker.target} is paused`,
        detail: breaker.reason,
        href: "/auto-apply",
        tone: "text-warning",
      });
    }
  }
  if (counts.unknown) {
    notices.push({
      key: "unknown",
      icon: CircleAlert,
      title: `${counts.unknown} submission outcome(s) unknown`,
      detail: "Check the employer's page or your email, then record what happened.",
      href: "/auto-apply",
      tone: "text-warning",
    });
  }
  if (counts.inbox) {
    notices.push({
      key: "inbox",
      icon: Inbox,
      title: `${counts.inbox} question(s) need your answer`,
      detail: "Answer once; every application waiting on it is filled.",
      href: "/action-inbox",
      tone: "text-violet",
    });
  }
  const pendingSuggestions = suggestions.data?.length ?? 0;
  if (pendingSuggestions) {
    notices.push({
      key: "email",
      icon: Mail,
      title: `${pendingSuggestions} status change(s) suggested by email`,
      detail: "Accept or dismiss each one; nothing is applied automatically.",
      href: "/email",
      tone: "text-cyan",
    });
  }

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="icon" aria-label={`Notifications (${notices.length})`} className="relative">
          <Bell />
          {notices.length ? (
            <span className="absolute right-1.5 top-1.5 size-2 rounded-full bg-violet ring-2 ring-background" />
          ) : null}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 p-0">
        <div className="border-b border-line px-4 py-3">
          <p className="text-sm font-semibold text-text-1">Needs your attention</p>
        </div>
        {notices.length === 0 ? (
          <p className="px-4 py-8 text-center text-xs text-text-3">Nothing is waiting on you.</p>
        ) : (
          <ul className="max-h-80 divide-y divide-line overflow-y-auto">
            {notices.map((notice) => (
              <li key={notice.key}>
                <Link href={notice.href} className="flex gap-3 px-4 py-3 transition-colors hover:bg-surface-2">
                  <notice.icon className={`mt-0.5 size-4 shrink-0 ${notice.tone}`} />
                  <div className="min-w-0">
                    <p className="text-[13px] font-medium text-text-1">{notice.title}</p>
                    <p className="mt-0.5 line-clamp-2 text-xs text-text-3">{notice.detail}</p>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </PopoverContent>
    </Popover>
  );
}
