import Link from "next/link";
import { SiteHeader } from "@/components/site-header";

export default function NotFound() {
  return (
    <>
      <SiteHeader backHref="/" backLabel="All clusters" />
      <main className="flex-1 mx-auto max-w-6xl px-6 py-24 flex flex-col items-start gap-6">
        <p className="text-[11px] uppercase tracking-[0.22em] text-muted-foreground">
          404 · cluster not found
        </p>
        <h1 className="font-display text-4xl md:text-6xl tracking-tight text-foreground max-w-[20ch]">
          No cluster matches that ID.
        </h1>
        <p className="text-muted-foreground max-w-prose">
          The <code className="font-mono">cluster_id</code> in the URL
          doesn&rsquo;t appear in{" "}
          <code className="font-mono">workspace.demo.cluster_review_export</code>
          . It may have been replaced by a newer clustering run, or the URL is
          mistyped.
        </p>
        <Link
          href="/"
          className="text-[11px] uppercase tracking-[0.18em] text-brand hover:underline"
        >
          ← Back to all clusters
        </Link>
      </main>
    </>
  );
}
