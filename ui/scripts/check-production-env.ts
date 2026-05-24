import { Client } from "pg";

/**
 * Production environment and database connection readiness checker.
 * Can be run in pre-deployment CI/CD, release phases, or manually.
 */
async function runReadinessCheck() {
  console.log("==================================================");
  console.log("  Astroturf Control Plane Production Readiness   ");
  console.log("==================================================\n");

  const deploymentMode = process.env.ASTROTURF_DEPLOYMENT_MODE;
  const executionMode = process.env.ASTROTURF_EXECUTION_MODE;
  const enableJobSubmit = process.env.ASTROTURF_ENABLE_JOB_SUBMIT === "true";
  const databaseUrl = process.env.DATABASE_URL;

  console.log(`[Config] ASTROTURF_DEPLOYMENT_MODE: ${deploymentMode || "undefined (defaulting to development)"}`);
  console.log(`[Config] ASTROTURF_EXECUTION_MODE: ${executionMode || "undefined"}`);
  console.log(`[Config] ASTROTURF_ENABLE_JOB_SUBMIT: ${enableJobSubmit ? "true" : "false"}\n`);

  let hasErrors = false;

  // 1. Validate Database URL
  if (!databaseUrl || !databaseUrl.trim()) {
    console.error("❌ ERROR: DATABASE_URL is not set or empty.");
    hasErrors = true;
  } else {
    console.log("✅ DATABASE_URL is configured.");
    
    // 2. Connect to PostgreSQL and verify required tables
    console.log("Connecting to PostgreSQL...");
    const isLocalhost = databaseUrl.includes("localhost") || databaseUrl.includes("127.0.0.1");
    const sslConfig = isLocalhost ? false : { rejectUnauthorized: false };
    
    const client = new Client({
      connectionString: databaseUrl,
      ssl: sslConfig,
    });

    try {
      await client.connect();
      console.log("✅ Successfully established connection to PostgreSQL.");

      const requiredTables = [
        "docket_catalog",
        "analysis_requests",
        "watchlist_items",
        "autopilot_runs"
      ];

      console.log("Verifying control-plane tables exist...");
      for (const table of requiredTables) {
        const res = await client.query(
          `SELECT EXISTS (
             SELECT FROM information_schema.tables 
             WHERE table_schema = 'public' 
             AND table_name = $1
           )`,
          [table]
        );
        const exists = res.rows[0]?.exists;
        if (exists) {
          console.log(`  ✅ Table '${table}' exists.`);
        } else {
          console.error(`  ❌ ERROR: Required table '${table}' is MISSING in public schema.`);
          console.error(`     Ensure you run migrations from 'ui/db/migrations/' first!`);
          hasErrors = true;
        }
      }
      
      await client.end();
    } catch (dbErr) {
      console.error("❌ ERROR: Failed to connect to PostgreSQL database:", dbErr);
      hasErrors = true;
    }
  }

  // 3. Verify Databricks variables if job submission is active
  const isDatabricksMode = executionMode === "databricks_job" || enableJobSubmit;
  if (isDatabricksMode) {
    console.log("\nVerifying Databricks Cloud Environment Configuration...");
    const requiredDbVars = [
      "DATABRICKS_HOST",
      "DATABRICKS_TOKEN",
      "DATABRICKS_JOB_ID"
    ];

    for (const v of requiredDbVars) {
      const val = process.env[v];
      if (!val || !val.trim()) {
        console.error(`❌ ERROR: Missing required environment variable for Databricks Job execution: ${v}`);
        hasErrors = true;
      } else {
        // Safe obscuring of token
        const displayVal = v === "DATABRICKS_TOKEN" 
          ? `dapi...${val.trim().substring(val.trim().length - 4)}` 
          : val.trim();
        console.log(`  ✅ ${v} is configured: ${displayVal}`);
      }
    }
  }

  console.log("\n==================================================");
  if (hasErrors) {
    console.error("❌ PRODUCTION READINESS CHECK: FAILED.");
    console.error("Please address the failures listed above before deploying.");
    console.log("==================================================");
    process.exit(1);
  } else {
    console.log("🎉 PRODUCTION READINESS CHECK: SUCCESS!");
    console.log("The Astroturf Control Plane is production-ready.");
    console.log("==================================================");
    process.exit(0);
  }
}

runReadinessCheck().catch((err) => {
  console.error("Unhandled execution exception in readiness checker:", err);
  process.exit(1);
});
