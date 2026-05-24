import { formatInt } from "@/lib/format";
import { cn } from "@/lib/utils";

interface StatStripProps {
  largestCampaign: number;
  campaignsDetected: number;
  commentsInCampaigns: number;
  totalComments: number;
}

export function StatStrip({
  largestCampaign,
  campaignsDetected,
  commentsInCampaigns,
  totalComments,
}: StatStripProps) {
  return (
    <section className="border-b border-rule">
      <div className="mx-auto max-w-6xl px-6 py-12 md:py-14">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-x-8 gap-y-10">
          <Stat
            label="Largest campaign size"
            value={largestCampaign}
            accent
            emphasize
          />
          <Stat label="Coordinated campaigns" value={campaignsDetected} />
          <Stat label="Comments in campaigns" value={commentsInCampaigns} />
          <Stat label="Total comments analyzed" value={totalComments} />
        </div>
      </div>
    </section>
  );
}

function Stat({
  label,
  value,
  accent,
  emphasize,
}: {
  label: string;
  value: number;
  accent?: boolean;
  emphasize?: boolean;
}) {
  return (
    <div className="flex flex-col">
      <span
        className={cn(
          "font-display leading-none tabular-nums",
          emphasize
            ? "text-5xl md:text-7xl"
            : "text-4xl md:text-6xl",
          accent ? "text-brand" : "text-foreground",
        )}
      >
        {formatInt(value)}
      </span>
      <span className="mt-3 text-[11px] font-sans uppercase tracking-[0.16em] text-muted-foreground">
        {label}
      </span>
    </div>
  );
}
