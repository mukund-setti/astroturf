import Link from "next/link";
import { cn } from "@/lib/utils";
import { DataDiagnostics } from "@/components/data-diagnostics";
import { getDataDiagnostics, getDataSourceLabel } from "@/lib/databricks";

interface SiteHeaderProps {
  backHref?: string;
  backLabel?: string;
}

export function SiteHeader({ backHref, backLabel }: SiteHeaderProps) {
  const dataSourceLabel = getDataSourceLabel();
  const diagnostics = getDataDiagnostics();

  return (
    <header className="sticky top-0 z-30 border-b border-rule/60 bg-background/85 backdrop-blur-md">
      <div className="mx-auto max-w-6xl px-6 py-3.5 flex items-center justify-between gap-4">
        <div className="flex items-center gap-7">
          <Link
            href="/"
            className="group flex items-center gap-2 font-display text-lg tracking-tight text-foreground"
          >
            <span
              aria-hidden="true"
              className="inline-block h-2 w-2 rounded-full bg-brand transition-transform duration-200 group-hover:scale-125"
            />
            <span className="group-hover:text-brand transition-colors">Astroturf</span>
          </Link>
          <nav className="hidden md:flex items-center gap-1 text-sm text-muted-foreground">
            <NavLink href="/discoveries">Discoveries</NavLink>
            <NavLink href="/watchlist">Watchlist</NavLink>
            <NavLink href="/monitor">Monitor</NavLink>
            <NavLink href="/analyze">Advanced</NavLink>
            <NavLink href="/analysis">Queue</NavLink>
          </nav>
        </div>

        {backHref ? (
          <Link
            href={backHref}
            className={cn(
              "text-sm text-muted-foreground hover:text-brand transition-colors",
              "inline-flex items-center gap-1.5",
            )}
          >
            <span aria-hidden="true">←</span>
            <span>{backLabel ?? "Back"}</span>
          </Link>
        ) : null}
      </div>
      <div className="border-t border-rule/40 bg-card/50">
        <div className="mx-auto max-w-6xl px-6 py-1.5 flex items-center justify-between gap-4 text-xs text-muted-foreground/80">
          <span className="inline-flex items-center gap-2">
            <span aria-hidden="true" className="inline-block h-1.5 w-1.5 rounded-full bg-emerald-500/70" />
            <span>{dataSourceLabel}</span>
          </span>
          <DataDiagnostics diagnostics={diagnostics} />
        </div>
      </div>
    </header>
  );
}

function NavLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link
      href={href}
      className="rounded-md px-2.5 py-1.5 text-sm font-medium text-foreground/70 hover:text-foreground hover:bg-secondary/60 transition-colors"
    >
      {children}
    </Link>
  );
}
