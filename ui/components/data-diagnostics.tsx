import type { DataDiagnostics as DataDiagnosticsPayload } from "@/lib/databricks";

interface DataDiagnosticsProps {
  diagnostics: DataDiagnosticsPayload;
}

export function DataDiagnostics({ diagnostics }: DataDiagnosticsProps) {
  const source =
    diagnostics.resolvedSource === "live"
      ? "SQL"
      : diagnostics.resolvedSource === "fallback"
        ? "Fallback artifacts"
        : "Pending";

  const statusClass =
    diagnostics.status === "error"
      ? "text-red-700"
      : diagnostics.status === "fallback"
        ? "text-amber-700"
        : "text-muted-foreground";

  return (
    <details className="group relative">
      <summary className="cursor-pointer list-none text-[10px] uppercase tracking-[0.16em] text-muted-foreground hover:text-foreground transition-colors">
        Data diagnostics
      </summary>
      <div className="absolute right-0 mt-2 w-[min(22rem,calc(100vw-3rem))] rounded-sm border border-rule bg-card p-3 shadow-[0_10px_30px_-16px_rgba(26,23,20,0.35)] z-50">
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-[11px] leading-relaxed">
          <dt className="text-muted-foreground">Mode</dt>
          <dd className="font-mono text-foreground">{diagnostics.dataMode}</dd>
          <dt className="text-muted-foreground">Source</dt>
          <dd className="font-mono text-foreground">{source}</dd>
          <dt className="text-muted-foreground">Docket</dt>
          <dd className="font-mono text-foreground">{diagnostics.docketId}</dd>
          <dt className="text-muted-foreground">Table</dt>
          <dd className="font-mono text-foreground break-all">
            {diagnostics.table}
          </dd>
          <dt className="text-muted-foreground">Catalog</dt>
          <dd className="font-mono text-foreground">{diagnostics.catalog}</dd>
          <dt className="text-muted-foreground">Rows</dt>
          <dd className="font-mono text-foreground">
            {diagnostics.rowCount === null ? "n/a" : diagnostics.rowCount}
          </dd>
          <dt className="text-muted-foreground">Status</dt>
          <dd className={`font-mono ${statusClass}`}>{diagnostics.status}</dd>
        </dl>
        {diagnostics.error ? (
          <p className="mt-2 border-t border-rule pt-2 text-[11px] leading-relaxed text-red-700">
            {diagnostics.error}
          </p>
        ) : null}
      </div>
    </details>
  );
}
