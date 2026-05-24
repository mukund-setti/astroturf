export type ExecutionMode = "command" | "local_process" | "databricks_job";

/**
 * Returns the currently active execution mode.
 * Evaluates environment variables with proper fallback defaults:
 * - Production defaults to "databricks_job" if Databricks credentials exist, otherwise "command".
 * - Development/other environments default to "command".
 */
export function getExecutionMode(): ExecutionMode {
  // 1. Backward compatibility check
  if (process.env.ASTROTURF_ENABLE_JOB_SUBMIT === "true") {
    return "databricks_job";
  }

  const mode = process.env.ASTROTURF_EXECUTION_MODE;
  if (mode === "command" || mode === "local_process" || mode === "databricks_job") {
    return mode;
  }

  // 2. Defaulting logic based on hosting environment
  if (process.env.NODE_ENV === "production") {
    const hasDatabricksVars =
      process.env.DATABRICKS_JOB_ID &&
      process.env.DATABRICKS_HOST &&
      process.env.DATABRICKS_TOKEN;
    
    if (hasDatabricksVars) {
      return "databricks_job";
    }
    return "command";
  }

  // Development default
  return "command";
}

/**
 * Maps the execution mode to a human-readable display label.
 */
export function getExecutionModeLabel(mode: ExecutionMode): string {
  switch (mode) {
    case "command":
      return "Command-generation mode";
    case "local_process":
      return "Local developer execution mode";
    case "databricks_job":
      return "Databricks Jobs mode";
  }
}

/**
 * Server-side safety validator to prevent long-running python process spawning
 * in deployed hosted production/serverless environments.
 */
export function validateExecutionModeServer(): void {
  const mode = getExecutionMode();
  if (process.env.NODE_ENV === "production" && mode === "local_process") {
    throw new Error(
      "Local process execution is disabled in production. Use Databricks Jobs mode."
    );
  }
}
