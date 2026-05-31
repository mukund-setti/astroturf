import type { StatsPayload, ClusterSummary, ClusterDetailPayload, ClusterRow, Source } from "./types";

export type DataMode = "mock" | "live" | "auto";
type ResolvedDataSource = "live" | "fallback";
export interface DataDiagnostics {
  dataMode: DataMode;
  resolvedSource: ResolvedDataSource | "unknown";
  docketId: string;
  catalog: string;
  table: string;
  rowCount: number | null;
  status: "not_queried" | "ok" | "fallback" | "error";
  error: string | null;
}

type NamedParamValue =
  | string
  | number
  | bigint
  | boolean
  | Date
  | null
  | undefined;
type NamedParams = Record<string, NamedParamValue>;
let lastResolvedDataSource: ResolvedDataSource | null = null;
let lastQueryDiagnostics: Omit<
  DataDiagnostics,
  "dataMode" | "docketId" | "catalog"
> = {
  resolvedSource: "unknown",
  table: "workspace.demo.cluster_review_export",
  rowCount: null,
  status: "not_queried",
  error: null,
};

interface StatsRow {
  total_comments?: unknown;
  cluster_count?: unknown;
  comments_in_clusters?: unknown;
  largest_cluster_size?: unknown;
}

interface ClusterSummaryRow {
  cluster_id: string;
  cluster_size: unknown;
  similarity_threshold: unknown;
  embedding_model: string;
  representative_comment_id: string;
  rep_text_preview: string | null;
  rep_submitter_name: string | null;
  rep_posted_date: unknown;
  earliest_posted_date: unknown;
  latest_posted_date: unknown;
}

interface ClusterDetailRow {
  cluster_id: string;
  cluster_size: unknown;
  similarity_threshold: unknown;
  embedding_model: string;
  representative_comment_id: string;
  comment_id: string;
  is_representative: unknown;
  text_source: string | null;
  text_preview: string | null;
  submitter_name: string | null;
  posted_date: unknown;
  source: Source | null;
  exported_at: unknown;
}

export interface PipelineOutputCounts {
  raw_comments: number;
  parsed_comments: number;
  export_rows: number;
  export_clusters: number;
}

function hasEnv(name: string): boolean {
  const value = process.env[name];
  return !!value && value.trim() !== "";
}

function hasDatabricksSqlEnv(): boolean {
  return (
    hasEnv("DATABRICKS_HOST") &&
    hasEnv("DATABRICKS_TOKEN") &&
    hasEnv("DATABRICKS_HTTP_PATH")
  );
}

export function getDataMode(): DataMode {
  if (process.env.OFFLINE_MODE === "true") {
    return "mock";
  }

  const raw = (process.env.ASTROTURF_DATA_MODE ?? "auto").trim().toLowerCase();
  if (raw === "mock" || raw === "live" || raw === "auto") {
    return raw;
  }

  console.warn(
    `Invalid ASTROTURF_DATA_MODE="${raw}". Expected mock, live, or auto; using auto.`,
  );
  return "auto";
}

export function getDataSourceLabel(): string {
  const mode = getDataMode();

  if (mode === "live") {
    return "Live Databricks SQL mode";
  }
  if (mode === "mock") {
    return "Offline benchmark artifact mode";
  }
  if (lastResolvedDataSource === "fallback") {
    return "Auto mode: using fallback artifacts";
  }
  if (lastResolvedDataSource === "live") {
    return "Live Databricks SQL mode";
  }
  if (hasDatabricksSqlEnv()) {
    return "Live Databricks SQL mode";
  }
  return "Auto mode: using fallback artifacts";
}

export function getDataDiagnostics(): DataDiagnostics {
  return {
    dataMode: getDataMode(),
    docketId: getDocketId(),
    catalog: getCatalog(),
    ...lastQueryDiagnostics,
  };
}

export function isOfflineMode(): boolean {
  const mode = getDataMode();
  return mode === "mock" || (mode === "auto" && !hasDatabricksSqlEnv());
}

export function getCatalog(): string {
  // IMPORTANT: this default must match the catalog default used when
  // submitting Databricks jobs from `submitDocketJob` in
  // `ui/lib/databricks-jobs.ts`. Historically these two helpers
  // disagreed ("workspace" here vs. "astroturf" there), so the
  // Databricks job would write to `astroturf.bronze.raw_comments`
  // while the UI queried `workspace.bronze.raw_comments`, always
  // getting zero rows and erroneously marking the run as failed.
  const raw = (process.env.DATABRICKS_CATALOG ?? "astroturf").trim();
  return raw;
}

export function getDocketId(): string {
  if (isOfflineMode()) {
    return "17-108";
  }
  return (process.env.DEMO_DOCKET_ID ?? "17-108").trim();
}

export function toInt(value: unknown): number {
  if (value === null || value === undefined) return 0;
  if (typeof value === "number") return value;
  if (typeof value === "bigint") return Number(value);
  if (typeof value === "string") {
    const n = Number(value);
    return Number.isNaN(n) ? 0 : n;
  }
  if (typeof value === "object" && value !== null && "toNumber" in value) {
    const fn = (value as { toNumber?: unknown }).toNumber;
    if (typeof fn === "function") return (fn as () => number).call(value);
  }
  return 0;
}

export function toIso(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (value instanceof Date) return value.toISOString();
  if (typeof value === "string") return value;
  return null;
}

/**
 * Returns lakehouse row counts for ``docketId`` if and only if we can
 * actually query the live Databricks SQL warehouse. Returns ``null``
 * when verification is not possible, i.e. when the UI is in mock mode,
 * in auto mode without SQL credentials configured, or when the live
 * query failed and the data layer silently fell back to mock fixtures.
 *
 * Callers must treat ``null`` as "unknown, could not verify" rather
 * than "verified empty". A previous bug here returned ``{0, 0, 0, 0}``
 * in mock/fallback mode, which caused successful Databricks runs to be
 * falsely re-marked as failed.
 */
export async function getPipelineOutputCounts(
  docketId: string,
): Promise<PipelineOutputCounts | null> {
  if (!canQueryLakehouse()) {
    return null;
  }

  const catalog = getCatalog();
  const sql = `
    SELECT
      (SELECT COUNT(*)
         FROM ${catalog}.bronze.raw_comments
         WHERE docket_id = :docket_id)
        AS raw_comments,
      (SELECT COUNT(*)
         FROM ${catalog}.silver.parsed_comments
         WHERE docket_id = :docket_id)
        AS parsed_comments,
      (SELECT COUNT(*)
         FROM ${catalog}.demo.cluster_review_export
         WHERE docket_id = :docket_id)
        AS export_rows,
      (SELECT COUNT(DISTINCT cluster_id)
         FROM ${catalog}.demo.cluster_review_export
         WHERE docket_id = :docket_id)
        AS export_clusters
  `;
  let rows: Record<string, unknown>[];
  try {
    rows = await query<Record<string, unknown>>(sql, { docket_id: docketId });
  } catch (err) {
    console.warn(
      `getPipelineOutputCounts: live SQL query failed for docket_id=${docketId}; treating counts as unknown.`,
      err,
    );
    return null;
  }

  if (lastResolvedDataSource !== "live") {
    return null;
  }

  const row = rows[0] ?? {};
  return {
    raw_comments: toInt(row.raw_comments),
    parsed_comments: toInt(row.parsed_comments),
    export_rows: toInt(row.export_rows),
    export_clusters: toInt(row.export_clusters),
  };
}

export interface DetailedStageCounts {
  raw_comments: number;
  parsed_comments: number;
  comment_embeddings: number;
  clusters: number;
  cluster_memberships: number;
  export_rows: number;
  export_clusters: number;
}

/**
 * Live per-stage row counts for a docket, queried directly off the Delta
 * paths via the SQL warehouse. Used by the auto-polling analysis detail
 * page to render "Stage 2/5: parsing — 12,431 of 20,697 rows" while a
 * Databricks notebook is still mid-run.
 *
 * Each stage is queried independently and any single failure leaves -1
 * in that slot instead of throwing. Historically the dropouts came from
 * the delta-rs FUSE bypass making paths transiently unreadable during
 * its rmtree→copytree window (see ADR-0017); even after H1 swapped that
 * for Spark MERGE we keep the -1 sentinel because Spark transactions can
 * still leave a path briefly inconsistent for a downstream reader.
 * Callers should render -1 as "syncing…" rather than "zero rows".
 *
 * Returns null when live SQL is not available (mock mode, missing
 * warehouse env vars, etc.), with the same contract as
 * `getPipelineOutputCounts`.
 */
export async function getDetailedStageCounts(
  docketId: string,
): Promise<DetailedStageCounts | null> {
  if (!canQueryLakehouse()) {
    return null;
  }

  const dataRoot = (
    process.env.DATABRICKS_DATA_ROOT ?? "/Volumes/astroturf/demo/exports/_lakehouse"
  ).replace(/\/+$/, "");
  const catalog = getCatalog();

  const counts: DetailedStageCounts = {
    raw_comments: -1,
    parsed_comments: -1,
    comment_embeddings: -1,
    clusters: -1,
    cluster_memberships: -1,
    export_rows: -1,
    export_clusters: -1,
  };

  const queries: Array<[keyof DetailedStageCounts, string]> = [
    [
      "raw_comments",
      `SELECT COUNT(*) AS n FROM delta.\`${dataRoot}/bronze/raw_comments\` WHERE docket_id = :docket_id`,
    ],
    [
      "parsed_comments",
      `SELECT COUNT(*) AS n FROM delta.\`${dataRoot}/silver/parsed_comments\` WHERE docket_id = :docket_id`,
    ],
    [
      "comment_embeddings",
      `SELECT COUNT(*) AS n FROM delta.\`${dataRoot}/silver/comment_embeddings\` WHERE docket_id = :docket_id`,
    ],
    [
      "clusters",
      `SELECT COUNT(*) AS n FROM delta.\`${dataRoot}/gold/comment_clusters\` WHERE docket_id = :docket_id`,
    ],
    [
      "cluster_memberships",
      `SELECT COUNT(*) AS n FROM delta.\`${dataRoot}/gold/comment_cluster_memberships\` WHERE docket_id = :docket_id`,
    ],
    [
      "export_rows",
      `SELECT COUNT(*) AS n FROM ${catalog}.demo.cluster_review_export WHERE docket_id = :docket_id`,
    ],
    [
      "export_clusters",
      `SELECT COUNT(DISTINCT cluster_id) AS n FROM ${catalog}.demo.cluster_review_export WHERE docket_id = :docket_id`,
    ],
  ];

  await Promise.all(
    queries.map(async ([key, sql]) => {
      try {
        const rows = await query<{ n: unknown }>(sql, { docket_id: docketId });
        if (lastResolvedDataSource === "live") {
          counts[key] = toInt(rows[0]?.n);
        }
      } catch (err) {
        console.warn(
          `getDetailedStageCounts: ${key} read failed (likely mid-FUSE-sync):`,
          sanitizeDiagnosticMessage(err),
        );
      }
    }),
  );

  return counts;
}

/**
 * Reports whether the UI process can actually execute live SQL against
 * the Databricks lakehouse. False when running in offline/mock mode or
 * when auto mode cannot find the required SQL warehouse env vars.
 */
function canQueryLakehouse(): boolean {
  const mode = getDataMode();
  if (mode === "mock") return false;
  if (!hasDatabricksSqlEnv()) return false;
  return true;
}

export async function query<T = Record<string, unknown>>(
  sql: string,
  namedParameters: NamedParams = {},
): Promise<T[]> {
  const mode = getDataMode();
  const sqlEnvReady = hasDatabricksSqlEnv();

  if (mode === "mock" || (mode === "auto" && !sqlEnvReady)) {
    lastResolvedDataSource = "fallback";
    const rows = executeMockQuery<T>(sql, namedParameters);
    recordQueryDiagnostics(sql, rows.length, "fallback", null);
    return rows;
  }

  if (mode === "live" && !sqlEnvReady) {
    throw new Error(
      "ASTROTURF_DATA_MODE=live requires DATABRICKS_HOST, DATABRICKS_TOKEN, and DATABRICKS_HTTP_PATH.",
    );
  }

  const host = (process.env.DATABRICKS_HOST ?? "").trim().replace(/^https?:\/\//, "").replace(/\/+$/, "");
  const path = (process.env.DATABRICKS_HTTP_PATH ?? "").trim();
  const token = (process.env.DATABRICKS_TOKEN ?? "").trim();

  try {
    const { DBSQLClient } = await import("@databricks/sql");
    const client = new DBSQLClient();
    await client.connect({ host, path, token });
    const session = await client.openSession();
    try {
      const operation = await session.executeStatement(sql, { namedParameters });
      try {
        const rows = await operation.fetchAll();
        lastResolvedDataSource = "live";
        recordQueryDiagnostics(sql, rows.length, "ok", null);
        return rows as T[];
      } finally {
        await operation.close();
      }
    } finally {
      await session.close();
      await client.close();
    }
  } catch (err) {
    const message = sanitizeDiagnosticMessage(err);
    if (mode === "live") {
      lastResolvedDataSource = "live";
      const formatted = formatLiveDatabricksError(message);
      recordQueryDiagnostics(sql, null, "error", formatted);
      throw new Error(formatted, {
        cause: err,
      });
    }

    console.warn(
      "DATABRICKS QUERY FAILURE. Active environment variables failed to connect.",
      message,
      "\nGracefully falling back to local offline showcase artifacts..."
    );
    lastResolvedDataSource = "fallback";
    const rows = executeMockQuery<T>(sql, namedParameters);
    recordQueryDiagnostics(sql, rows.length, "fallback", message);
    return rows;
  }
}

function recordQueryDiagnostics(
  sql: string,
  rowCount: number | null,
  status: "ok" | "fallback" | "error",
  error: string | null,
): void {
  lastQueryDiagnostics = {
    resolvedSource: lastResolvedDataSource ?? "unknown",
    table: inferPrimaryTable(sql),
    rowCount,
    status,
    error,
  };
}

function inferPrimaryTable(sql: string): string {
  const normalized = sql.replace(/\s+/g, " ");
  const matches = [...normalized.matchAll(/\bFROM\s+([A-Za-z0-9_.]+)/gi)];
  return matches.at(-1)?.[1] ?? `${getCatalog()}.demo.cluster_review_export`;
}

function formatLiveDatabricksError(message: string): string {
  const safeMessage = redactPrivateIdentifiers(message);
  if (message.includes("401")) {
    return [
      "Databricks SQL authentication failed with HTTP 401.",
      "Check DATABRICKS_TOKEN, confirm the token is not expired or revoked, and verify the principal has access to the SQL Warehouse in DATABRICKS_HTTP_PATH.",
      `Driver message: ${safeMessage}`,
    ].join(" ");
  }

  if (message.includes("403")) {
    return [
      "Databricks SQL authorization failed with HTTP 403.",
      "The token is valid, but the principal likely lacks permission on the SQL Warehouse, catalog, schema, or table.",
      `Driver message: ${safeMessage}`,
    ].join(" ");
  }

  return `Databricks SQL query failed in live mode. Driver message: ${safeMessage}`;
}

function sanitizeDiagnosticMessage(value: unknown): string {
  if (value instanceof Error) {
    return redactPrivateIdentifiers(value.message);
  }
  return redactPrivateIdentifiers(String(value));
}

function redactPrivateIdentifiers(message: string): string {
  return message
    .replace(/https?:\/\/[A-Za-z0-9.-]+\.cloud\.databricks\.com/gi, "https://<databricks-workspace-host>")
    .replace(/\/sql\/1\.0\/warehouses\/[A-Za-z0-9-]+/gi, "/sql/1.0/warehouses/<warehouse-id>")
    .replace(/dapi[A-Za-z0-9]+/gi, "<databricks-token>")
    .replace(/Bearer\s+[A-Za-z0-9._~+/=-]+/gi, "Bearer <redacted>")
    .replace(/postgres(?:ql)?:\/\/[^\s"'`]+/gi, "<postgres-connection-url>");
}

/**
 * Transparent mock database provider supplying high-fidelity campaign data
 * for ECFS docket 17-108 (Net Neutrality) corresponding to example runs and receipts.
 */
function executeMockQuery<T>(sql: string, params: NamedParams): T[] {
  const queryStr = sql.toLowerCase();

  if (queryStr.includes("select") && queryStr.includes("total_comments")) {
    return [
      {
        total_comments: 4993,
        cluster_count: 3,
        comments_in_clusters: 1017,
        largest_cluster_size: 1002,
      },
    ] as unknown as T[];
  }

  // 2. CLUSTERS SUMMARY LIST MOCK
  if (queryStr.includes("group by") && queryStr.includes("cluster_id")) {
    return [
      {
        cluster_id: "96413d57e367d1abc8cec9a73ac260017105fa797802ba319eb300015444817c",
        cluster_size: 1002,
        similarity_threshold: 0.92,
        embedding_model: "BAAI/bge-large-en-v1.5",
        representative_comment_id: "10828445130115",
        rep_text_preview: "We need the FCC to defend the rights of millions of Internet users by upholding net neutrality protections. I stand with the millions of other Internet users who’ve urged the Commission to keep important net neutrality protections intact...",
        rep_submitter_name: "Anonymous Citizen",
        rep_posted_date: "2017-08-28T19:00:02.000Z",
        earliest_posted_date: "2017-08-28T17:00:02.000Z",
        latest_posted_date: "2017-08-28T19:00:02.000Z",
      },
      {
        cluster_id: "753fb0e2d898c0f0d1dbd7070b6e1fcb1a839da537e2e757b238cba2d3b75906",
        cluster_size: 13,
        similarity_threshold: 0.92,
        embedding_model: "BAAI/bge-large-en-v1.5",
        representative_comment_id: "10828063717964",
        rep_text_preview: "Net neutrality has created an unreliable landscape for consumers and businesses alike. We need Congress to bring clarity to this debate.",
        rep_submitter_name: "Anonymous Citizen",
        rep_posted_date: "2017-08-28T19:00:02.000Z",
        earliest_posted_date: "2017-08-28T19:00:02.000Z",
        latest_posted_date: "2017-08-28T19:00:02.000Z",
      },
      {
        cluster_id: "73c8d60afb009ba76673e9218d60f0ef0ebaa39f421de2f1bc24040a4aeaedb3",
        cluster_size: 2,
        similarity_threshold: 0.92,
        embedding_model: "BAAI/bge-large-en-v1.5",
        representative_comment_id: "108282615031038",
        rep_text_preview: "I urge FCC Chairman Ajit Pai to preserve real Net Neutrality under the FCC’s existing rules and keep broadband internet access classified under Title II.",
        rep_submitter_name: "Anonymous Citizen",
        rep_posted_date: "2017-08-28T19:00:02.000Z",
        earliest_posted_date: "2017-08-28T19:00:02.000Z",
        latest_posted_date: "2017-08-28T19:00:02.000Z",
      },
    ] as unknown as T[];
  }

  // 3. CLUSTER DETAIL ROUTE MOCK
  if (queryStr.includes("where cluster_id =") || queryStr.includes("is_representative")) {
    const clusterId = (params.cluster_id || "").toString();
    const rows = getMockClusterRows(clusterId);
    return rows as unknown as T[];
  }

  return [] as T[];
}

function getMockClusterRows(clusterId: string): Record<string, unknown>[] {
  const shortId = clusterId.substring(0, 12);

  if (clusterId.startsWith("epa_exact_hash_cluster")) {
    const isCluster1 = clusterId === "epa_exact_hash_cluster_1";
    const isCluster2 = clusterId === "epa_exact_hash_cluster_2";
    
    if (isCluster1) {
      const medoid = {
        cluster_id: "epa_exact_hash_cluster_1",
        cluster_size: 4,
        similarity_threshold: 1.0,
        embedding_model: "exact_hash",
        representative_comment_id: "epa_comment_1",
        comment_id: "epa_comment_1",
        is_representative: true,
        text_source: "detail_comment_text",
        text_preview: "As a concerned citizen, I write to urge the EPA to implement the strongest possible standards to limit methane and volatile organic compound (VOC) emissions from new and existing oil and gas sources. Safe communities require strict oversight and transparency from industrial operators.",
        submitter_name: "Anonymous Citizen",
        posted_date: "2021-12-08T15:00:00.000Z",
        source: "exact_hash",
        exported_at: "2026-05-24T05:11:59.000Z",
      };

      const members = Array.from({ length: 3 }, (_, i) => ({
        cluster_id: "epa_exact_hash_cluster_1",
        cluster_size: 4,
        similarity_threshold: 1.0,
        embedding_model: "exact_hash",
        representative_comment_id: "epa_comment_1",
        comment_id: `epa_comment_1_${i + 2}`,
        is_representative: false,
        text_source: "detail_comment_text",
        text_preview: "As a concerned citizen, I write to urge the EPA to implement the strongest possible standards to limit methane and volatile organic compound (VOC) emissions from new and existing oil and gas sources. Safe communities require strict oversight and transparency from industrial operators.",
        submitter_name: `Audited Citizen #${i + 1}`,
        posted_date: "2021-12-08T15:05:00.000Z",
        source: "exact_hash",
        exported_at: "2026-05-24T05:11:59.000Z",
        similarity: 1.0,
      }));

      return [medoid, ...members];
    } else if (isCluster2) {
      const medoid = {
        cluster_id: "epa_exact_hash_cluster_2",
        cluster_size: 3,
        similarity_threshold: 1.0,
        embedding_model: "exact_hash",
        representative_comment_id: "epa_comment_5",
        comment_id: "epa_comment_5",
        is_representative: true,
        text_source: "detail_comment_text",
        text_preview: "The proposed Standards of Performance represent a vital step forward in combating our global climate emergency. I strongly support the EPA's focus on leak detection and repair (LDAR) intervals and eliminating venting at well sites.",
        submitter_name: "Anonymous Citizen",
        posted_date: "2021-12-08T15:30:00.000Z",
        source: "exact_hash",
        exported_at: "2026-05-24T05:11:59.000Z",
      };

      const members = Array.from({ length: 2 }, (_, i) => ({
        cluster_id: "epa_exact_hash_cluster_2",
        cluster_size: 3,
        similarity_threshold: 1.0,
        embedding_model: "exact_hash",
        representative_comment_id: "epa_comment_5",
        comment_id: `epa_comment_5_${i + 6}`,
        is_representative: false,
        text_source: "detail_comment_text",
        text_preview: "The proposed Standards of Performance represent a vital step forward in combating our global climate emergency. I strongly support the EPA's focus on leak detection and repair (LDAR) intervals and eliminating venting at well sites.",
        submitter_name: `Climate Advocate #${i + 1}`,
        posted_date: "2021-12-08T15:32:00.000Z",
        source: "exact_hash",
        exported_at: "2026-05-24T05:11:59.000Z",
        similarity: 1.0,
      }));

      return [medoid, ...members];
    } else {
      const medoid = {
        cluster_id: "epa_exact_hash_cluster_3",
        cluster_size: 2,
        similarity_threshold: 1.0,
        embedding_model: "exact_hash",
        representative_comment_id: "epa_comment_8",
        comment_id: "epa_comment_8",
        is_representative: true,
        text_source: "detail_comment_text",
        text_preview: "Cutting climate pollution from the oil and gas sector is the single fastest and most cost-effective way to slow global warming. Our families deserve clean air and a stable climate.",
        submitter_name: "Anonymous Citizen",
        posted_date: "2021-12-08T16:00:00.000Z",
        source: "exact_hash",
        exported_at: "2026-05-24T05:11:59.000Z",
      };

      const member = {
        cluster_id: "epa_exact_hash_cluster_3",
        cluster_size: 2,
        similarity_threshold: 1.0,
        embedding_model: "exact_hash",
        representative_comment_id: "epa_comment_8",
        comment_id: "epa_comment_9",
        is_representative: false,
        text_source: "detail_comment_text",
        text_preview: "Cutting climate pollution from the oil and gas sector is the single fastest and most cost-effective way to slow global warming. Our families deserve clean air and a stable climate.",
        submitter_name: "Eco Supporter #1",
        posted_date: "2021-12-08T16:01:00.000Z",
        source: "exact_hash",
        exported_at: "2026-05-24T05:11:59.000Z",
        similarity: 1.0,
      };

      return [medoid, member];
    }
  }

  if (shortId === "96413d57e367") {
    const medoid = {
      cluster_id: "96413d57e367d1abc8cec9a73ac260017105fa797802ba319eb300015444817c",
      cluster_size: 1002,
      similarity_threshold: 0.92,
      embedding_model: "BAAI/bge-large-en-v1.5",
      representative_comment_id: "10828445130115",
      comment_id: "10828445130115",
      is_representative: true,
      text_source: "detail_comment_text",
      text_preview: "We need the FCC to defend the rights of millions of Internet users by upholding net neutrality protections. I stand with the millions of other Internet users who’ve urged the Commission to keep important net neutrality protections intact. \r\n\r\nThe FCC should reject Chairman Ajit Pai’s proposal to hand the government-subsidized telecom giants like AT&T, Verizon, and Comcast free rein to create Internet fast lanes, stripping Internet users of the necessary privacy and access rules we demanded and just recently won. \r\n\r\nI’m afraid of a “pay-to-play” Internet where ISPs can charge more for certain websites because ISPs could have too much power to determine what I can do online. Thankfully, the existing net neutrality rules mean that Internet providers can’t slow or block customers’ ability to see certain web services or create Internet “fast lanes” by charging online services and websites more money to reach customers faster. That’s exactly the right balance to make sure competition in the Internet space is fair and benefits consumers and small businesses as well as larger players. Pai’s proposed repeal of the rules would transform ISPs into gatekeepers with an effective veto right on expression and innovation. That’s contrary to the basic precepts on which the Internet was built. \r\n\r\nIt Means Everything to me. \r\n\r\nThank you for keeping Title II net neutrality rules in place to protect Internet users like me.",
      submitter_name: "Anonymous Citizen",
      posted_date: "2017-08-28T19:00:02.000Z",
      source: "semantic",
      exported_at: "2026-05-24T05:11:59.000Z",
    };

    const members = [
      {
        cluster_id: "96413d57e367d1abc8cec9a73ac260017105fa797802ba319eb300015444817c",
        cluster_size: 1002,
        similarity_threshold: 0.92,
        embedding_model: "BAAI/bge-large-en-v1.5",
        representative_comment_id: "10828445130115",
        comment_id: "108282535307158",
        is_representative: false,
        text_source: "detail_comment_text",
        text_preview: "We need the FCC to defend the rights of millions of Internet users by upholding net neutrality protections. I stand with the millions of other Internet users who’ve urged the Commission to keep important net neutrality protections intact. \r\n\r\nThe FCC should reject Chairman Ajit Pai’s plan to hand the government-subsidized ISP monopolies like Verizon, Comcast, and AT&T the legal cover to create Internet fast lanes, stripping consumers of the meaningful access and privacy protections we demanded and won just two years ago. \r\n\r\nI’m afraid of a “pay-to-play” Internet where ISPs can charge more for certain websites because ISPs could have too much power to determine what I can do online. Thankfully, the current FCC regulations ensure that Internet providers can’t slow or block users’ access to certain web services or create Internet “fast lanes” by charging online services and websites money to reach customers faster. That’s exactly the right balance to make sure competition in the Internet space is fair and benefits small businesses and Internet users as well as larger players. Pai’s proposed repeal of the rules would help turn Internet providers into Internet gatekeepers with the ability to veto new innovation and expression. That’s not the kind of Internet we want to pass on to future generations of technology users. \r\n\r\nI grew up with our internet and throughout my time I have had great times with our internet on a variety of sites and this new plan could take away things that make the internet what it really is. A free network connecting millions. \r\n\r\nThank you for keeping Title II net neutrality rules in place to protect Internet users like me.",
        submitter_name: "Eleanor Vance",
        posted_date: "2017-08-28T19:00:02.000Z",
        source: "semantic",
        exported_at: "2026-05-24T05:11:59.000Z",
        similarity: 0.9903,
      },
      {
        cluster_id: "96413d57e367d1abc8cec9a73ac260017105fa797802ba319eb300015444817c",
        cluster_size: 1002,
        similarity_threshold: 0.92,
        embedding_model: "BAAI/bge-large-en-v1.5",
        representative_comment_id: "10828445130115",
        comment_id: "1082893935836",
        is_representative: false,
        text_source: "detail_comment_text",
        text_preview: "We need the FCC to defend the rights of millions of Internet users by upholding net neutrality protections. I stand with the millions of other Internet users who’ve urged the Commission to keep important net neutrality protections intact. \r\n\r\nThe FCC should reject Chairman Ajit Pai’s proposal to hand the government-subsidized ISP monopolies like Comcast, Verizon, and AT&T free rein to engage in data discrimination, stripping users of the necessary privacy and access safeguards we worked for and so recently won. \r\n\r\nI’m worried about creating a tiered Internet with “fast lanes” for certain sites or services because ISPs could have too much power to determine what I can do online. Thankfully, the existing Open Internet Open Internet rules mean that ISPs can’t slow or block our access to certain web services or create Internet “fast lanes” by charging websites and online services money to reach consumers faster. That’s exactly the right balance to ensure the Internet remains a level playing field that benefits consumers and small businesses as well as entrenched Internet companies. Chairman Pai’s proposed repeal of the rules would help turn ISPs into Internet gatekeepers with the ability to veto new expression and innovation. That’s not the kind of Internet we want to pass on to future generations of technology users. \r\n\r\nI appreciate you maintaining Title II net neutrality rules and the rights of Internet users like me.",
        submitter_name: "Gregory House",
        posted_date: "2017-08-28T17:00:02.000Z",
        source: "semantic",
        exported_at: "2026-05-24T05:11:59.000Z",
        similarity: 0.9839,
      },
      {
        cluster_id: "96413d57e367d1abc8cec9a73ac260017105fa797802ba319eb300015444817c",
        cluster_size: 1002,
        similarity_threshold: 0.92,
        embedding_model: "BAAI/bge-large-en-v1.5",
        representative_comment_id: "10828445130115",
        comment_id: "108280080014462",
        is_representative: false,
        text_source: "detail_comment_text",
        text_preview: "We need the FCC to defend the rights of millions of Internet users by upholding net neutrality protections. I stand with the millions of other Internet users who’ve urged the Commission to keep important net neutrality protections intact. \r\n\r\nThe FCC should reject Chairman Ajit Pai’s proposal to give the ISP monopolies like Comcast, Verizon, and AT&T free rein to give access rules, stripping consumers of the meaningful privacy and access safeguards we worked for and won just two years ago. \r\n\r\nI’m afraid of a “pay-to-play” Internet where ISPs can charge more for certain websites because ISPs could have too much power to determine what I can do online. Thankfully, the current Open Internet Open Internet rules mean that ISP monopolies can’t slow or block our access to certain web services or create Internet “fast lanes” by charging websites and online services more money to reach people faster. That’s exactly the right balance to ensure the Internet remains a level playing field that benefits consumers and small businesses as well as larger players. Pai’s proposed repeal of the rules would help turn Internet providers into Internet gatekeepers with the ability to veto new expression and innovation. That’s contrary to the basic precepts on which the Internet was built. \r\n\r\nThe internet belongs to everyone. \r\n\r\nThanks for protecting Internet users like me by upholding the existing Title II net neutrality rules.",
        submitter_name: "Robert Chase",
        posted_date: "2017-08-28T19:00:02.000Z",
        source: "semantic",
        exported_at: "2026-05-24T05:11:59.000Z",
        similarity: 0.9831,
      },
    ];

    return [medoid, ...members];
  }

  if (shortId === "753fb0e2d898") {
    const medoid = {
      cluster_id: "753fb0e2d898c0f0d1dbd7070b6e1fcb1a839da537e2e757b238cba2d3b75906",
      cluster_size: 13,
      similarity_threshold: 0.92,
      embedding_model: "BAAI/bge-large-en-v1.5",
      representative_comment_id: "10828063717964",
      comment_id: "10828063717964",
      is_representative: true,
      text_source: "detail_comment_text",
      text_preview: "Net neutrality has created an unreliable landscape for consumers and businesses alike. We need Congress to bring clarity to this debate.",
      submitter_name: "Anonymous Citizen",
      posted_date: "2017-08-28T19:00:02.000Z",
      source: "semantic",
      exported_at: "2026-05-24T05:11:59.000Z",
    };

    const members = Array.from({ length: 12 }, (_, i) => ({
      cluster_id: "753fb0e2d898c0f0d1dbd7070b6e1fcb1a839da537e2e757b238cba2d3b75906",
      cluster_size: 13,
      similarity_threshold: 0.92,
      embedding_model: "BAAI/bge-large-en-v1.5",
      representative_comment_id: "10828063717964",
      comment_id: `108280718318885-${i}`,
      is_representative: false,
      text_source: "detail_comment_text",
      text_preview: "Net neutrality has created an unreliable landscape for consumers and businesses alike. We need Congress to bring clarity to this debate.",
      submitter_name: `System Lobbyist #${i + 1}`,
      posted_date: "2017-08-28T19:00:02.000Z",
      source: "semantic",
      exported_at: "2026-05-24T05:11:59.000Z",
      similarity: 1.0000,
    }));

    return [medoid, ...members];
  }

  if (shortId === "73c8d60afb00") {
    const medoid = {
      cluster_id: "73c8d60afb009ba76673e9218d60f0ef0ebaa39f421de2f1bc24040a4aeaedb3",
      cluster_size: 2,
      similarity_threshold: 0.92,
      embedding_model: "BAAI/bge-large-en-v1.5",
      representative_comment_id: "108282615031038",
      comment_id: "108282615031038",
      is_representative: true,
      text_source: "detail_comment_text",
      text_preview: "I urge FCC Chairman Ajit Pai to preserve real Net Neutrality under the FCC’s existing rules and keep broadband internet access classified under Title II.",
      submitter_name: "Anonymous Citizen",
      posted_date: "2017-08-28T19:00:02.000Z",
      source: "semantic",
      exported_at: "2026-05-24T05:11:59.000Z",
    };

    const member = {
      cluster_id: "73c8d60afb009ba76673e9218d60f0ef0ebaa39f421de2f1bc24040a4aeaedb3",
      cluster_size: 2,
      similarity_threshold: 0.92,
      embedding_model: "BAAI/bge-large-en-v1.5",
      representative_comment_id: "108282615031038",
      comment_id: "108282763324605",
      is_representative: false,
      text_source: "detail_comment_text",
      text_preview: "I urge FCC Chairman Ajit Pai to preserve real Net Neutrality under the FCC’s existing rules and keep broadband internet access classified under Title II.",
      submitter_name: "Allison Cameron",
      posted_date: "2017-08-28T19:00:02.000Z",
      source: "semantic",
      exported_at: "2026-05-24T05:11:59.000Z",
      similarity: 1.0000,
    };

    return [medoid, member];
  }

  return [];
}

/**
 * Direct server-side data access fetchers. Bypasses Next.js HTTP loop during static pre-rendering,
 * solving the compile-time ECONNREFUSED network failure entirely.
 */
export async function getStatsPayload(docketIdParam?: string): Promise<StatsPayload> {
  const catalog = getCatalog();
  const docketId = docketIdParam || getDocketId();

  const sql = `
    SELECT
      COALESCE(
        NULLIF((
          SELECT COUNT(*)
          FROM ${catalog}.silver.parsed_comments
          WHERE docket_id = :docket_id
        ), 0),
        (
          SELECT COUNT(DISTINCT comment_id)
          FROM ${catalog}.demo.cluster_review_export
          WHERE docket_id = :docket_id
        ),
        0
      ) AS total_comments,
      COALESCE(
        NULLIF((
          SELECT COUNT(DISTINCT cluster_id)
          FROM ${catalog}.demo.cluster_review_export
          WHERE docket_id = :docket_id AND source = 'semantic'
        ), 0),
        (
          SELECT COUNT(DISTINCT cluster_id)
          FROM ${catalog}.demo.cluster_review_export
          WHERE docket_id = :docket_id
        ),
        0
      ) AS cluster_count,
      COALESCE(
        NULLIF((
          SELECT COUNT(DISTINCT comment_id)
          FROM ${catalog}.demo.cluster_review_export
          WHERE docket_id = :docket_id AND source = 'semantic'
        ), 0),
        (
          SELECT COUNT(DISTINCT comment_id)
          FROM ${catalog}.demo.cluster_review_export
          WHERE docket_id = :docket_id
        ),
        0
      ) AS comments_in_clusters,
      COALESCE(
        NULLIF((
          SELECT MAX(cluster_size)
          FROM ${catalog}.demo.cluster_review_export
          WHERE docket_id = :docket_id AND source = 'semantic'
        ), 0),
        (
          SELECT MAX(cluster_size)
          FROM ${catalog}.demo.cluster_review_export
          WHERE docket_id = :docket_id
        ),
        0
      ) AS largest_cluster_size
  `;

  const rows = await query<StatsRow>(sql, { docket_id: docketId });
  const row = rows[0] ?? {};

  return {
    total_comments: toInt(row.total_comments),
    cluster_count: toInt(row.cluster_count),
    comments_in_clusters: toInt(row.comments_in_clusters),
    largest_cluster_size: toInt(row.largest_cluster_size),
    docket_id: docketId,
  };
}

export function getValidatedDemoStatsPayload(): StatsPayload {
  const rows = executeMockQuery<StatsRow>(
    "SELECT total_comments, cluster_count, comments_in_clusters, largest_cluster_size",
    {},
  );
  const row = rows[0] ?? {};
  return {
    total_comments: toInt(row.total_comments),
    cluster_count: toInt(row.cluster_count),
    comments_in_clusters: toInt(row.comments_in_clusters),
    largest_cluster_size: toInt(row.largest_cluster_size),
    docket_id: "17-108",
  };
}

export async function getClustersSummary(docketIdParam?: string): Promise<ClusterSummary[]> {
  const catalog = getCatalog();
  const docketId = docketIdParam || getDocketId();

  const sql = `
    WITH scoped_export AS (
      SELECT *
      FROM ${catalog}.demo.cluster_review_export
      WHERE docket_id = :docket_id
        AND (
          source = 'semantic'
          OR NOT EXISTS (
            SELECT 1
            FROM ${catalog}.demo.cluster_review_export
            WHERE docket_id = :docket_id AND source = 'semantic'
          )
        )
    )
    SELECT
      cluster_id,
      cluster_size,
      similarity_threshold,
      embedding_model,
      representative_comment_id,
      MAX(CASE WHEN is_representative THEN text_preview END)
        AS rep_text_preview,
      MAX(CASE WHEN is_representative THEN submitter_name END)
        AS rep_submitter_name,
      MAX(CASE WHEN is_representative THEN posted_date END)
        AS rep_posted_date,
      MIN(posted_date) AS earliest_posted_date,
      MAX(posted_date) AS latest_posted_date
    FROM scoped_export
    GROUP BY
      cluster_id,
      cluster_size,
      similarity_threshold,
      embedding_model,
      representative_comment_id
    ORDER BY cluster_size DESC, cluster_id ASC
  `;

  const rows = await query<ClusterSummaryRow>(sql, { docket_id: docketId });

  return rows.map((r) => ({
    cluster_id: r.cluster_id,
    cluster_size: toInt(r.cluster_size),
    similarity_threshold: Number(r.similarity_threshold ?? 0),
    embedding_model: r.embedding_model,
    representative_comment_id: r.representative_comment_id,
    rep_text_preview: r.rep_text_preview,
    rep_submitter_name: r.rep_submitter_name,
    rep_posted_date: toIso(r.rep_posted_date),
    earliest_posted_date: toIso(r.earliest_posted_date),
    latest_posted_date: toIso(r.latest_posted_date),
  }));
}

export function getValidatedDemoClustersSummary(): ClusterSummary[] {
  return executeMockQuery<ClusterSummaryRow>(
    "SELECT cluster_id FROM demo.cluster_review_export GROUP BY cluster_id",
    {},
  ).map((r) => ({
    cluster_id: r.cluster_id,
    cluster_size: toInt(r.cluster_size),
    similarity_threshold: Number(r.similarity_threshold ?? 0),
    embedding_model: r.embedding_model,
    representative_comment_id: r.representative_comment_id,
    rep_text_preview: r.rep_text_preview,
    rep_submitter_name: r.rep_submitter_name,
    rep_posted_date: toIso(r.rep_posted_date),
    earliest_posted_date: toIso(r.earliest_posted_date),
    latest_posted_date: toIso(r.latest_posted_date),
  }));
}

export async function getClusterDetail(
  clusterId: string,
): Promise<ClusterDetailPayload | null> {
  const catalog = getCatalog();

  const sql = `
    SELECT
      cluster_id,
      cluster_size,
      similarity_threshold,
      embedding_model,
      representative_comment_id,
      comment_id,
      is_representative,
      text_source,
      text_preview,
      submitter_name,
      posted_date,
      source,
      exported_at
    FROM ${catalog}.demo.cluster_review_export
    WHERE cluster_id = :cluster_id
    ORDER BY is_representative DESC, posted_date ASC
  `;

  const rows = await query<ClusterDetailRow>(sql, { cluster_id: clusterId });

  const mapped: ClusterRow[] = rows.map((r) => ({
    cluster_id: r.cluster_id,
    cluster_size: toInt(r.cluster_size),
    similarity_threshold: Number(r.similarity_threshold ?? 0),
    embedding_model: r.embedding_model,
    representative_comment_id: r.representative_comment_id,
    comment_id: r.comment_id,
    is_representative: Boolean(r.is_representative),
    text_source: r.text_source,
    text_preview: r.text_preview,
    submitter_name: r.submitter_name,
    posted_date: toIso(r.posted_date),
    source: (r.source as Source) ?? "semantic",
    exported_at: toIso(r.exported_at),
  }));

  if (mapped.length === 0) {
    return null;
  }

  return {
    cluster_id: clusterId,
    rows: mapped,
  };
}
