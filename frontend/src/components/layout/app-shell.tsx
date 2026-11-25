import { AppSidebar } from "./app-sidebar";
import { CommandPaletteProvider } from "./command-palette";
import { Topbar } from "./topbar";

/** Sidebar + top bar around every workspace page. */
export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <CommandPaletteProvider>
      <div className="flex min-h-dvh">
        <AppSidebar />
        <div className="flex min-w-0 flex-1 flex-col">
          <Topbar />
          <main className="orbit-ambient flex-1">
            <div className="mx-auto w-full max-w-[var(--content-max)] px-[var(--space-page-x)] py-[var(--space-page-y)]">
              {children}
            </div>
          </main>
        </div>
      </div>
    </CommandPaletteProvider>
  );
}
