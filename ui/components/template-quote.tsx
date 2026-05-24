import { formatDate } from "@/lib/format";
import type { ClusterRow } from "@/lib/types";

interface TemplateQuoteProps {
  representative: ClusterRow;
}

export function TemplateQuote({ representative }: TemplateQuoteProps) {
  const postedDate = formatDate(representative.posted_date);
  const text = representative.text_preview ?? "";

  return (
    <section className="mx-auto max-w-6xl px-6 py-14 md:py-16">
      <p className="text-[11px] uppercase tracking-[0.22em] text-muted-foreground mb-6">
        The representative template
      </p>

      <blockquote className="relative bg-brand-soft border-l-[3px] border-l-brand p-8 md:p-12">
        {text ? (
          <p className="font-display text-lg md:text-2xl text-foreground leading-relaxed max-w-[64ch] whitespace-pre-wrap">
            &ldquo;{text}&rdquo;
          </p>
        ) : (
          <p className="font-display text-base text-muted-foreground italic">
            (no text preview available for the representative comment)
          </p>
        )}

        <footer className="mt-8 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] uppercase tracking-[0.16em] text-muted-foreground">
          <span className="font-mono normal-case tracking-normal text-xs">
            {representative.comment_id}
          </span>

          {postedDate ? (
            <>
              <span aria-hidden className="text-rule">
                ·
              </span>
              <span className="tabular-nums">{postedDate}</span>
            </>
          ) : null}

          <span aria-hidden className="text-rule">
            ·
          </span>
          {representative.submitter_name ? (
            <span className="normal-case tracking-normal text-xs">
              {representative.submitter_name}
            </span>
          ) : (
            <span className="italic normal-case tracking-normal text-xs">
              (unsigned)
            </span>
          )}

          {representative.text_source ? (
            <>
              <span aria-hidden className="text-rule">
                ·
              </span>
              <span className="font-mono normal-case tracking-normal text-[11px]">
                source: {representative.text_source}
              </span>
            </>
          ) : null}
        </footer>
      </blockquote>

      <p className="mt-3 text-[11px] text-muted-foreground">
        Preview truncated to ~500 characters per the export contract. Full text
        remains in <code className="font-mono">silver.parsed_comments</code>.
      </p>
    </section>
  );
}
