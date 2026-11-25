import {
  Activity,
  BarChart3,
  Bookmark,
  Bot,
  Building2,
  ClipboardCheck,
  Compass,
  FileUser,
  GraduationCap,
  Inbox,
  Layers,
  LayoutDashboard,
  Mail,
  Radar,
  Send,
  Settings,
  type LucideIcon,
} from "lucide-react";

/** Counts the sidebar can show. Each is backed by a real endpoint (see useNavCounts). */
export type NavCountKey = "inbox" | "review" | "unknown";

export interface NavItem {
  title: string;
  href: string;
  icon: LucideIcon;
  description: string;
  count?: NavCountKey;
  keywords?: string[];
}

export interface NavGroup {
  label: string;
  items: NavItem[];
}

export const NAVIGATION: NavGroup[] = [
  {
    label: "Workspace",
    items: [
      {
        title: "Dashboard",
        href: "/dashboard",
        icon: LayoutDashboard,
        description: "Your job-search pipeline at a glance",
        keywords: ["home", "overview"],
      },
    ],
  },
  {
    label: "Discover",
    items: [
      {
        title: "Job discovery",
        href: "/jobs",
        icon: Compass,
        description: "Search, filter and inspect matched jobs",
        keywords: ["search", "feed", "listings"],
      },
      {
        title: "Saved jobs",
        href: "/saved",
        icon: Bookmark,
        description: "Jobs you shortlisted",
        keywords: ["shortlist", "bookmarks"],
      },
    ],
  },
  {
    label: "Apply",
    items: [
      {
        title: "Bulk preparation",
        href: "/bulk",
        icon: Layers,
        description: "Prepare many applications in one run",
        keywords: ["batch"],
      },
      {
        title: "Auto-apply",
        href: "/auto-apply",
        icon: Bot,
        description: "Preflight, approve and run submissions",
        count: "unknown",
        keywords: ["preflight", "submit", "runs", "emergency"],
      },
      {
        title: "Applications",
        href: "/applications",
        icon: Send,
        description: "Track every application and outcome",
        keywords: ["tracker", "status"],
      },
      {
        title: "Action inbox",
        href: "/action-inbox",
        icon: Inbox,
        description: "Questions only you can answer",
        count: "inbox",
        keywords: ["answers", "missing"],
      },
      {
        title: "Review queue",
        href: "/review-queue",
        icon: ClipboardCheck,
        description: "Prepared applications waiting for you",
        count: "review",
        keywords: ["approve"],
      },
    ],
  },
  {
    label: "Prepare",
    items: [
      {
        title: "Resume and profile",
        href: "/profile",
        icon: FileUser,
        description: "Resume, profile and verified answers",
        keywords: ["resume", "cv", "skills"],
      },
      {
        title: "Company research",
        href: "/company-research",
        icon: Building2,
        description: "Cited facts about employers",
        keywords: ["company"],
      },
      {
        title: "Interview prep",
        href: "/interview-prep",
        icon: GraduationCap,
        description: "Questions, practice and round notes",
        keywords: ["interview", "mock"],
      },
    ],
  },
  {
    label: "Insights",
    items: [
      {
        title: "Analytics",
        href: "/analytics",
        icon: BarChart3,
        description: "Outcomes from recorded data only",
        keywords: ["metrics", "funnel"],
      },
      {
        title: "Email tracking",
        href: "/email",
        icon: Mail,
        description: "Replies matched to applications",
        keywords: ["gmail", "inbox"],
      },
    ],
  },
  {
    label: "System",
    items: [
      {
        title: "Sources",
        href: "/sources",
        icon: Radar,
        description: "Where jobs come from",
        keywords: ["boards", "greenhouse", "lever"],
      },
      {
        title: "Logs and diagnostics",
        href: "/logs",
        icon: Activity,
        description: "Audit trail and source health",
        keywords: ["audit", "health"],
      },
      {
        title: "Settings",
        href: "/settings",
        icon: Settings,
        description: "Preferences and installation",
        keywords: ["theme", "config"],
      },
    ],
  },
];

export const ALL_NAV_ITEMS: NavItem[] = NAVIGATION.flatMap((group) => group.items);

export function navItemFor(pathname: string): NavItem | undefined {
  return [...ALL_NAV_ITEMS]
    .sort((a, b) => b.href.length - a.href.length)
    .find((item) => pathname === item.href || pathname.startsWith(`${item.href}/`));
}
