const W = 800;
const TILE_X = 220;
const TILE_W = 360;
const ARROW_X = TILE_X + TILE_W / 2;
const LEFT_LABEL_X = TILE_X - 20;
const RIGHT_LABEL_X = TILE_X + TILE_W + 28;

// We deliberately use inline `style` with CSS variables for SVG fills and
// strokes rather than Tailwind utility classes (`fill-brand`, `stroke-rule`,
// etc.). Tailwind's `fill-*` / `stroke-*` generation for custom theme tokens
// is not reliable across dev and production builds, while CSS variables
// referenced via inline `style` work in every renderer.
const STYLE = {
  bg: { fill: "var(--card)" },
  bgAccent: { fill: "var(--brand-soft)" },
  border: { stroke: "var(--rule)" },
  borderAccent: { stroke: "var(--brand)" },
  ink: { fill: "var(--foreground)" },
  muted: { fill: "var(--muted-foreground)" },
  brand: { fill: "var(--brand)" },
  rule: { fill: "var(--rule)", stroke: "var(--rule)" },
} as const;

const DISPLAY_FONT = "var(--font-display)";

interface TileProps {
  y: number;
  tier: string;
  title: string;
  subtitle?: string;
  tall?: boolean;
  accent?: boolean;
}

function Tile({ y, tier, title, subtitle, tall, accent }: TileProps) {
  const h = tall ? 92 : 64;
  return (
    <g>
      <text
        x={LEFT_LABEL_X}
        y={y + h / 2 + 4}
        textAnchor="end"
        style={STYLE.muted}
        fontSize="11"
        letterSpacing="1.5"
      >
        {tier}
      </text>
      <rect
        x={TILE_X}
        y={y}
        width={TILE_W}
        height={h}
        style={{
          ...(accent ? STYLE.bgAccent : STYLE.bg),
          ...(accent ? STYLE.borderAccent : STYLE.border),
        }}
        strokeWidth="1"
        rx="2"
      />
      <text
        x={TILE_X + 18}
        y={tall ? y + 34 : y + 30}
        style={STYLE.ink}
        fontSize="18"
        fontFamily={DISPLAY_FONT}
      >
        {title}
      </text>
      {subtitle && (
        <text
          x={TILE_X + 18}
          y={tall ? y + 60 : y + 50}
          style={STYLE.muted}
          fontSize="12"
        >
          {subtitle}
        </text>
      )}
    </g>
  );
}

interface ArrowProps {
  fromY: number;
  toY: number;
  agent: string;
  dbxFeature?: string;
  dbxSub?: string;
}

function Arrow({ fromY, toY, agent, dbxFeature, dbxSub }: ArrowProps) {
  const mid = (fromY + toY) / 2;
  return (
    <g>
      <line
        x1={ARROW_X}
        y1={fromY}
        x2={ARROW_X}
        y2={toY - 6}
        style={{ stroke: "var(--rule)" }}
        strokeWidth="1"
      />
      <polygon
        points={`${ARROW_X - 4},${toY - 6} ${ARROW_X + 4},${toY - 6} ${ARROW_X},${toY}`}
        style={{ fill: "var(--rule)" }}
      />
      <text
        x={RIGHT_LABEL_X}
        y={mid - 6}
        style={STYLE.ink}
        fontSize="14"
        fontWeight="500"
      >
        {agent}
      </text>
      {dbxFeature && (
        <text
          x={RIGHT_LABEL_X}
          y={mid + 12}
          style={STYLE.brand}
          fontSize="11"
          letterSpacing="1.5"
        >
          {dbxFeature}
        </text>
      )}
      {dbxSub && (
        <text
          x={RIGHT_LABEL_X}
          y={mid + 28}
          style={STYLE.muted}
          fontSize="11"
        >
          {dbxSub}
        </text>
      )}
    </g>
  );
}

export function ArchitectureDiagram() {
  const y0 = 20;
  const y1 = 170;
  const y2 = 320;
  const y3 = 470;
  const y4 = 640;
  const y5 = 810;
  const y6 = 960;

  const bot = (y: number, tall = false) => y + (tall ? 92 : 64);

  return (
    <section className="border-b border-rule">
      <div className="mx-auto max-w-6xl px-6 py-16 md:py-24">
        <p className="text-[11px] uppercase tracking-[0.22em] text-muted-foreground mb-4">
          The system
        </p>
        <h2 className="font-display text-3xl md:text-5xl tracking-tight text-foreground leading-tight max-w-3xl">
          Six agents over a medallion lakehouse.
        </h2>
        <p className="mt-6 text-base md:text-lg text-foreground/85 max-w-prose leading-relaxed">
          Each transition between tiers is an idempotent agent with its own
          contract. Databricks features are called out at every touch point.
        </p>

        <div className="mt-12 md:mt-16 max-w-3xl mx-auto">
          <svg
            viewBox={`0 0 ${W} 1040`}
            xmlns="http://www.w3.org/2000/svg"
            className="w-full h-auto"
            role="img"
            aria-labelledby="arch-title arch-desc"
          >
            <title id="arch-title">Astroturf architecture diagram</title>
            <desc id="arch-desc">
              Vertical data flow from regulations.gov through bronze, silver,
              gold, and demo Delta tables on Databricks Unity Catalog. Agent
              names label each transition; Databricks features (Unity Catalog,
              Workflows, Foundation Model API, Vector Search, SQL Connector)
              are called out where they appear.
            </desc>

            <Tile
              y={y0}
              tier="SOURCE"
              title="regulations.gov + FCC ECFS"
              subtitle="dual federal APIs / shared api.data.gov rate budget"
            />
            <Arrow
              fromY={bot(y0)}
              toY={y1}
              agent="IngestionAgent"
              dbxFeature="UNITY CATALOG + DELTA MERGE"
              dbxSub="idempotent / MLflow run per ingestion"
            />

            <Tile
              y={y1}
              tier="BRONZE"
              title="raw_comments"
              subtitle="Delta table / partitioned by docket_id"
            />
            <Arrow
              fromY={bot(y1)}
              toY={y2}
              agent="ParserAgent"
              dbxFeature="WORKFLOWS / SOURCE-AWARE"
              dbxSub="ECFS skips detail-fetch; regs.gov enriches"
            />

            <Tile
              y={y2}
              tier="SILVER"
              title="parsed_comments"
              subtitle="title, body, submitter, attachments cataloged"
            />
            <Arrow
              fromY={bot(y2)}
              toY={y3}
              agent="EmbeddingAgent"
              dbxFeature="FOUNDATION MODEL API"
              dbxSub="databricks-bge-large-en / 1024-d"
            />

            <Tile
              y={y3}
              tier="SILVER"
              title="comment_embeddings"
              subtitle="Delta table / synced to Vector Search index"
              tall
            />
            <Arrow
              fromY={bot(y3, true)}
              toY={y4}
              agent="ClusteringAgent"
              dbxFeature="VECTOR SEARCH"
              dbxSub="cosine over BGE index"
            />

            <Tile
              y={y4}
              tier="GOLD"
              title="comment_clusters"
              subtitle="+ cluster_memberships / template + members"
              tall
            />
            <Arrow
              fromY={bot(y4, true)}
              toY={y5}
              agent="Export"
              dbxSub="CTAS to demo schema"
            />

            <Tile
              y={y5}
              tier="DEMO"
              title="cluster_review_export"
              subtitle="denormalized, UI-ready / one row per (cluster, comment)"
            />
            <Arrow
              fromY={bot(y5)}
              toY={y6}
              agent="Next.js app"
              dbxFeature="SQL CONNECTOR"
            />

            <Tile
              y={y6}
              tier="APP"
              title="Astroturf UI"
              subtitle="this page / live queries, hourly revalidate"
              accent
            />
          </svg>
        </div>

        <div className="mt-10 md:mt-12 max-w-3xl mx-auto grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="border border-rule bg-card p-5 rounded-sm">
            <p className="text-[10px] uppercase tracking-[0.22em] text-brand font-medium mb-2">
              Side branch / AttributionAgent
            </p>
            <p className="text-xs text-muted-foreground leading-relaxed">
              Reads from <code className="font-mono text-foreground">gold.comment_clusters</code> and writes{" "}
              <code className="font-mono text-foreground">gold.campaign_attributions</code>. Offline-seed mode matches against a curated advocacy registry; tool-using LLM mode (web search + registry) gated behind ADR-0015.
            </p>
          </div>
          <div className="border border-rule bg-card p-5 rounded-sm">
            <p className="text-[10px] uppercase tracking-[0.22em] text-brand font-medium mb-2">
              Side branch / MigrationAgent
            </p>
            <p className="text-xs text-muted-foreground leading-relaxed">
              Compares cluster template language against final agency rule text and writes{" "}
              <code className="font-mono text-foreground">gold.rule_migrations</code> with phrase-level similarity, section citations, and mandatory caveat text. Federal Register API mode behind ADR-0015.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
