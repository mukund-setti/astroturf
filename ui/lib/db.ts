import { Pool } from "pg";

const isProduction = process.env.ASTROTURF_DEPLOYMENT_MODE === "production";
const databaseUrl = process.env.DATABASE_URL;

if (isProduction && (!databaseUrl || !databaseUrl.trim())) {
  throw new Error("CRITICAL CONFIGURATION ERROR: Missing required environment variable 'DATABASE_URL' in production deployment mode.");
}

let pool: Pool | null = null;

/**
 * Singleton database pool provider.
 * Ensures the connection pool is shared across hot-start lambda invocations.
 */
export function getDbPool(): Pool {
  if (pool) return pool;

  const resolvedUrl = databaseUrl || "";
  if (!resolvedUrl.trim()) {
    throw new Error("DATABASE_URL is not configured. Configure it in your environment variables.");
  }

  // Determine SSL settings (required for hosted platforms like Neon or Supabase)
  const isLocalhost = resolvedUrl.includes("localhost") || resolvedUrl.includes("127.0.0.1");
  const sslConfig = isLocalhost ? false : { rejectUnauthorized: false };

  pool = new Pool({
    connectionString: resolvedUrl,
    ssl: sslConfig,
    max: 10, // Max pooled connections to prevent hitting hosted db connection limits
    idleTimeoutMillis: 30000, // Timeout to close idle connections
    connectionTimeoutMillis: 5000, // Connection timeout threshold
  });

  pool.on("error", (err) => {
    console.error("Unexpected PostgreSQL client pool error:", err);
  });

  return pool;
}

/**
 * Execute a SQL query helper
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export async function query<T = any>(text: string, params?: any[]): Promise<T[]> {
  const db = getDbPool();
  const res = await db.query(text, params);
  return res.rows;
}
