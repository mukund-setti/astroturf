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
    <header className="border-b border-rule bg-background">
      <div className="mx-auto max-w-6xl px-6 py-4 flex items-center justify-between gap-4">
        <div className="flex items-center gap-8">
          <Link
            href="/"
            className="font-display text-lg tracking-tight text-foreground hover:text-brand transition-colors"
          >
            Astroturf
          </Link>
          <nav className="flex items-center gap-5 text-[10px] uppercase tracking-wider font-semibold text-muted-foreground/80">
            <Link href="/discoveries" className="hover:text-brand transition-colors">
              Discoveries
            </Link>
            <Link href="/watchlist" className="hover:text-brand transition-colors">
              Watchlist
            </Link>
            <Link href="/monitor" className="hover:text-brand transition-colors">
              Monitor
            </Link>
            <Link href="/analyze" className="hover:text-brand transition-colors">
              Advanced Config
            </Link>
            <Link href="/analysis" className="hover:text-brand transition-colors">
              Job Queue
            </Link>
          </nav>
        </div>

        {backHref ? (
          <Link
            href={backHref}
            className={cn(
              "text-[11px] uppercase tracking-[0.18em] text-muted-foreground",
              "hover:text-brand transition-colors",
            )}
          >
            ← {backLabel ?? "Back"}
          </Link>
        ) : null}
      </div>
      <div className="border-t border-rule/60 bg-card/40">
        <div className="mx-auto max-w-6xl px-6 py-1.5 flex items-center justify-between gap-4 text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
          <span>{dataSourceLabel}</span>
          <DataDiagnostics diagnostics={diagnostics} />
        </div>
      </div>
    </header>
  );
}
