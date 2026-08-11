import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";

import { navItems } from "./nav-items";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen w-full bg-background text-foreground">
      {/* Desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 hidden w-60 flex-col border-r border-border bg-sidebar px-4 py-6 md:flex">
        <div className="px-2">
          <p className="font-display text-lg leading-tight text-foreground">
            Personal
            <br />
            Observability
          </p>
          <p className="mt-2 text-xs text-muted-foreground">Private workspace</p>
        </div>

        <nav className="mt-8 flex flex-col gap-1">
          {navItems.map(({ to, label, icon: Icon, exact }) => (
            <Link
              key={to}
              to={to}
              activeOptions={{ exact: Boolean(exact) }}
              className="flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground data-[status=active]:bg-accent data-[status=active]:text-accent-foreground"
            >
              <Icon className="h-4 w-4 shrink-0" strokeWidth={1.75} />
              <span className="truncate">{label}</span>
            </Link>
          ))}
        </nav>

        <p className="mt-auto px-3 text-[11px] leading-relaxed text-muted-foreground">
          Nothing here is shared. Data stays yours.
        </p>
      </aside>

      {/* Main */}
      <div className="md:pl-60">
        <main className="mx-auto w-full max-w-2xl px-5 pt-8 pb-28 md:max-w-3xl md:pb-12">
          {children}
        </main>
      </div>

      {/* Mobile bottom navigation */}
      <nav className="fixed inset-x-0 bottom-0 z-20 border-t border-border bg-card/95 backdrop-blur md:hidden">
        {/* Column count follows navItems so adding a tab can't silently overflow.
            Inline style rather than a Tailwind class: `grid-cols-${n}` is built
            at runtime and would not survive Tailwind's static class scan. */}
        <ul
          className="grid"
          style={{ gridTemplateColumns: `repeat(${navItems.length}, minmax(0, 1fr))` }}
        >
          {navItems.map(({ to, label, icon: Icon, exact }) => (
            <li key={to} className="min-w-0">
              <Link
                to={to}
                activeOptions={{ exact: Boolean(exact) }}
                aria-label={label}
                className="flex flex-col items-center gap-1 px-1 py-2.5 text-[10px] text-muted-foreground transition-colors data-[status=active]:text-primary"
              >
                <Icon className="h-5 w-5 shrink-0" strokeWidth={1.75} />
                <span className="w-full truncate text-center">{label}</span>
              </Link>
            </li>
          ))}
        </ul>
        <div className="h-[env(safe-area-inset-bottom)]" />
      </nav>
    </div>
  );
}

export function PageHeader({
  title,
  subtitle,
  eyebrow,
}: {
  title?: string;
  subtitle?: string;
  eyebrow?: string;
}) {
  // A page may carry just an eyebrow when a full title would only restate it.
  // The eyebrow is promoted to the h1 in that case, keeping its small-caps look
  // but leaving the page with a real heading rather than none at all.
  const eyebrowIsHeading = !title;

  return (
    <header className={title || subtitle ? "mb-7" : "mb-5"}>
      {eyebrow ? (
        eyebrowIsHeading ? (
          <h1 className="text-[11px] tracking-[0.18em] uppercase text-muted-foreground">
            {eyebrow}
          </h1>
        ) : (
          <p className="mb-2 text-[11px] tracking-[0.18em] uppercase text-muted-foreground">
            {eyebrow}
          </p>
        )
      ) : null}
      {title ? (
        <h1 className="font-display text-2xl leading-tight text-foreground md:text-3xl">{title}</h1>
      ) : null}
      {subtitle ? <p className="mt-2 text-sm text-muted-foreground">{subtitle}</p> : null}
    </header>
  );
}

export function Placeholder({
  label,
  note,
  height = "h-28",
}: {
  label: string;
  note?: string;
  height?: string;
}) {
  return (
    <section className="rounded-xl border border-dashed border-border bg-card p-4">
      <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3">
        <h2 className="truncate text-sm font-medium text-foreground">{label}</h2>
        <span className="shrink-0 rounded-full bg-muted px-2 py-0.5 text-[10px] tracking-wide uppercase text-muted-foreground">
          Placeholder
        </span>
      </div>
      {note ? <p className="mt-1.5 text-xs text-muted-foreground">{note}</p> : null}
      <div
        className={`mt-3 ${height} rounded-lg bg-muted/60 grid place-items-center text-[11px] text-muted-foreground`}
      >
        No data yet
      </div>
    </section>
  );
}

export function PlaceholderRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 border-b border-border py-3 last:border-0">
      <span className="truncate text-sm text-foreground">{label}</span>
      <span className="shrink-0 text-xs text-muted-foreground">{value}</span>
    </div>
  );
}
