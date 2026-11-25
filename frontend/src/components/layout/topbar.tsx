"use client";

import { useQuery } from "@tanstack/react-query";
import {
  ChevronRight,
  FileUser,
  Menu,
  Moon,
  Plus,
  Radar,
  Search,
  Settings,
  Sparkles,
  Sun,
  Target,
  Layers,
} from "lucide-react";
import { useTheme } from "@/hooks/use-theme";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { OrbitMark, Wordmark } from "@/components/brand/orbit-mark";
import { NavLinks } from "@/components/navigation/nav-links";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Kbd } from "@/components/ui/kbd";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { api } from "@/lib/api/endpoints";
import { NAVIGATION, navItemFor } from "@/lib/constants/navigation";

import { useCommandPalette } from "./command-palette";
import { NotificationCenter } from "./notification-center";

function Breadcrumbs() {
  const pathname = usePathname();
  const item = navItemFor(pathname);
  const group = NAVIGATION.find((candidate) => candidate.items.includes(item!));
  const rest = item ? pathname.slice(item.href.length).split("/").filter(Boolean) : [];
  return (
    <nav aria-label="Breadcrumb" className="hidden min-w-0 items-center gap-1.5 text-[13px] md:flex">
      {group ? <span className="text-text-3">{group.label}</span> : null}
      {item ? (
        <>
          <ChevronRight className="size-3.5 text-text-3" />
          <Link href={item.href} className={rest.length ? "text-text-2 hover:text-text-1" : "font-medium text-text-1"}>
            {item.title}
          </Link>
        </>
      ) : null}
      {rest.map((segment, index) => (
        <span key={segment} className="flex items-center gap-1.5">
          <ChevronRight className="size-3.5 text-text-3" />
          <span className={index === rest.length - 1 ? "font-medium text-text-1" : "text-text-2"}>
            {/^\d+$/.test(segment) ? `#${segment}` : segment}
          </span>
        </span>
      ))}
    </nav>
  );
}

function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  // Both icons are rendered and CSS picks one, so the server's markup (which cannot know
  // the saved theme) matches the browser's and nothing flashes.
  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label="Toggle light and dark theme"
      onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
    >
      <Sun className="hidden dark:block" />
      <Moon className="dark:hidden" />
    </Button>
  );
}

function ProfileMenu() {
  const profile = useQuery({ queryKey: ["profile"], queryFn: api.profile });
  const name = profile.data?.full_name?.trim() || "Your profile";
  const initials =
    name
      .split(/\s+/)
      .map((part) => part[0])
      .join("")
      .slice(0, 2)
      .toUpperCase() || "Y";
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className="rounded-full outline-none ring-offset-2 ring-offset-background focus-visible:ring-2 focus-visible:ring-ring"
          aria-label="Profile menu"
        >
          <Avatar className="size-8 ring-1 ring-line-strong">
            <AvatarFallback className="bg-gradient-to-br from-violet/30 to-cyan/20 text-[11px] font-semibold text-text-1">
              {initials}
            </AvatarFallback>
          </Avatar>
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuLabel className="font-normal">
          <p className="truncate text-sm font-medium text-text-1">{name}</p>
          <p className="truncate text-xs text-text-3">{profile.data?.headline || profile.data?.email || "Local workspace"}</p>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link href="/profile">
            <FileUser /> Resume and profile
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <Link href="/settings">
            <Settings /> Settings
          </Link>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function QuickActions() {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button size="sm" className="hidden gap-1.5 shadow-glow sm:inline-flex">
          <Plus /> New
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
        <DropdownMenuItem asChild>
          <Link href="/jobs?discover=1">
            <Radar /> Discover jobs
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <Link href="/bulk">
            <Layers /> Prepare applications in bulk
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <Link href="/auto-apply">
            <Target /> Open auto-apply preflight
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <Link href="/action-inbox">
            <Sparkles /> Answer waiting questions
          </Link>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function GlobalSearch() {
  const router = useRouter();
  const palette = useCommandPalette();
  const [query, setQuery] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  // "/" focuses job search from anywhere, unless the user is already typing somewhere.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing =
        target?.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target?.tagName ?? "");
      if (event.key === "/" && !typing && !event.metaKey && !event.ctrlKey) {
        event.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  return (
    <form
      role="search"
      onSubmit={(event) => {
        event.preventDefault();
        const text = query.trim();
        router.push(text ? `/jobs?search=${encodeURIComponent(text)}` : "/jobs");
      }}
      className="relative hidden w-full max-w-xs md:block"
    >
      <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-text-3" />
      <input
        ref={inputRef}
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="Search jobs…"
        title="Press / to search"
        aria-label="Search jobs"
        className="h-8 w-full rounded-lg border border-line bg-surface-1 pl-8 pr-14 text-[13px] text-text-1 outline-none transition-colors placeholder:text-text-3 focus:border-violet/50 focus:ring-2 focus:ring-violet/20"
      />
      <button
        type="button"
        onClick={palette.open}
        className="absolute right-1.5 top-1/2 -translate-y-1/2"
        aria-label="Open command palette"
      >
        <Kbd className="text-[10px]">⌘K</Kbd>
      </button>
    </form>
  );
}

export function Topbar() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const palette = useCommandPalette();
  return (
    <header className="sticky top-0 z-30 flex h-[var(--topbar-height)] items-center gap-3 border-b border-line bg-background/75 px-4 backdrop-blur-xl lg:px-6">
      <Button
        variant="ghost"
        size="icon"
        className="lg:hidden"
        aria-label="Open navigation"
        onClick={() => setMobileOpen(true)}
      >
        <Menu />
      </Button>
      <Link href="/dashboard" className="flex items-center gap-2 lg:hidden">
        <OrbitMark className="size-6" />
        <Wordmark />
      </Link>
      <Breadcrumbs />
      <div className="ml-auto flex items-center gap-1.5">
        <GlobalSearch />
        <Button variant="ghost" size="icon" className="md:hidden" aria-label="Search" onClick={palette.open}>
          <Search />
        </Button>
        <QuickActions />
        <NotificationCenter />
        <ThemeToggle />
        <ProfileMenu />
      </div>
      <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
        <SheetContent side="left" className="w-72 border-sidebar-border bg-sidebar p-0">
          <SheetTitle className="flex h-[var(--topbar-height)] items-center gap-2.5 px-4">
            <OrbitMark />
            <Wordmark />
          </SheetTitle>
          <div className="overflow-y-auto px-3 pb-6">
            <NavLinks onNavigate={() => setMobileOpen(false)} />
          </div>
        </SheetContent>
      </Sheet>
    </header>
  );
}
