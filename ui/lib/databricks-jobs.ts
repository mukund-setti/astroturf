import type { AnalysisRequest } from "./analysis-store";

export interface DatabricksRunResponse {
  run_id: number;
  number_in_job: number;
  state: {
    life_cycle_state: "PENDING" | "RUNNING" | "TERMINATING" | "TERMINATED" | "SKIPPED" | "INTERNAL_ERROR";
    result_state?: "SUCCESS" | "FAILED" | "CANCELED" | "TIMEDOUT";
    state_message?: string;
  };
  tasks?: Array<{
    task_key: string;
    state: {
      life_cycle_state: string;
      result_state?: string;
      state_message?: string;
    };
  }>;
}

export function isJobSubmitEnabled(): boolean {
  return process.env.ASTROTURF_ENABLE_JOB_SUBMIT === "true";
}

function getEnvOrThrow(name: string): string {
  const value = process.env[name];
  if (!value || !value.trim()) {
    throw new Error(`Missing required Databricks environment variable: ${name}`);
  }
  return value.trim();
}

function getEnvOrDefault(name: string, fallback: string): string {
  const value = process.env[name];
  return value && value.trim() ? value.trim() : fallback;
}

/**
 * Submits a Databricks Job run for the given AnalysisRequest
 */
export async function submitDocketJob(request: AnalysisRequest): Promise<{ run_id: string }> {
  const jobId = getEnvOrThrow("DATABRICKS_JOB_ID");
  let host = getEnvOrThrow("DATABRICKS_HOST");
  const token = getEnvOrThrow("DATABRICKS_TOKEN");

  // Ensure host begins with https:// and has no trailing slash
  if (!host.startsWith("http://") && !host.startsWith("https://")) {
    host = `https://${host}`;
  }
  host = host.replace(/\/$/, "");

  const url = `${host}/api/2.1/jobs/run-now`;

  // The astroturf-analysis-pipeline job is configured with job-level parameters
  // (the Databricks "Job parameters" feature). The 2.1 API rejects notebook_params
  // for such jobs with "Cannot use legacy parameters ... because the job has job
  // parameters configured." So we send job_parameters: a flat string->string map
  // that the notebook reads via dbutils.widgets.get(...).
  //
  // CRITICAL: every widget the notebook reads must be pinned here. Any widget
  // we omit can be quietly overridden by stale notebook-task base_parameters
  // left in the workspace job definition (e.g. a manual smoke test that pinned
  // dry_run="true"), which causes the notebook to exit early with SUCCESS but
  // zero rows. Job parameters take precedence over base_parameters at runtime,
  // so pinning them defensively here is the correct guard.
  const payload = {
    job_id: parseInt(jobId, 10),
    job_parameters: {
      docket_id: request.docket_id,
      source: request.source,
      topic_id: request.topic_id,
      agency_id: request.agency_id,
      start_date: request.date_start || "null",
      end_date: request.date_end || "null",
      expected_scale: String(request.expected_scale),
      request_id: request.request_id,
      catalog: getEnvOrDefault("DATABRICKS_CATALOG", "astroturf"),
      data_root: getEnvOrDefault(
        "DATABRICKS_DATA_ROOT",
        "/Volumes/astroturf/demo/exports/_lakehouse"
      ),
      repo_path: getEnvOrDefault(
        "DATABRICKS_REPO_PATH",
        "/Workspace/Repos/<user>/astroturf"
      ),
      vector_index_name: getEnvOrDefault("DATABRICKS_VECTOR_INDEX_NAME", ""),
      clustering_mode: getEnvOrDefault("ASTROTURF_CLUSTERING_MODE", "vector_search"),
      similarity_threshold: getEnvOrDefault("ASTROTURF_SIMILARITY_THRESHOLD", "0.92"),
      // Hard-pin dry_run so a stale workspace base_parameter (e.g. left over
      // from a manual smoke test) cannot silently turn a real /analyze
      // submission into a zero-row no-op.
      dry_run: "false",
    },
  };

  try {
    const res = await fetch(url, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      if (res.status === 401 || res.status === 403) {
        throw new Error("Databricks authorization failed: Invalid or expired DATABRICKS_TOKEN.");
      }
      if (res.status === 404) {
        throw new Error("Configured Databricks Job was not found on the configured workspace.");
      }
      const errText = await res.text();
      throw new Error(`Databricks API returned HTTP ${res.status}: ${sanitizeDiagnosticMessage(errText)}`);
    }

    const data = await res.json();
    if (!data.run_id) {
      throw new Error("Databricks API run-now did not return a valid run_id.");
    }

    return { run_id: String(data.run_id) };
  } catch (err) {
    console.error("Databricks job submission failed:", sanitizeDiagnosticMessage(err));
    throw err;
  }
}

/**
 * Fetches the status of an ongoing Databricks run
 */
export async function getRunStatus(runId: string): Promise<DatabricksRunResponse> {
  let host = getEnvOrThrow("DATABRICKS_HOST");
  const token = getEnvOrThrow("DATABRICKS_TOKEN");

  if (!host.startsWith("http://") && !host.startsWith("https://")) {
    host = `https://${host}`;
  }
  host = host.replace(/\/$/, "");

  const url = `${host}/api/2.1/jobs/runs/get?run_id=${runId}`;

  try {
    const res = await fetch(url, {
      method: "GET",
      headers: {
        Authorization: `Bearer ${token}`,
      },
    });

    if (!res.ok) {
      if (res.status === 401 || res.status === 403) {
        throw new Error("Databricks authorization failed: Invalid or expired DATABRICKS_TOKEN.");
      }
      if (res.status === 404) {
        throw new Error(`Databricks Run with ID ${runId} was not found.`);
      }
      const errText = await res.text();
      throw new Error(`Databricks API returned HTTP ${res.status}: ${sanitizeDiagnosticMessage(errText)}`);
    }

    const data = await res.json();
    return data as DatabricksRunResponse;
  } catch (err) {
    console.error("Failed to fetch Databricks run status:", sanitizeDiagnosticMessage(err));
    throw err;
  }
}

/**
 * Fetches a notebook task's exit message (the string passed to
 * dbutils.notebook.exit). Returns null if the API does not surface one or the
 * fetch fails — callers should treat absence as "no exit message available"
 * rather than as an error, because this is purely diagnostic.
 *
 * For a multi-task job run we walk the first task's run_id, because that is
 * where the notebook_output lives. The parent job run's get-output endpoint
 * returns no notebook_output for multi-task jobs.
 */
export async function getNotebookExitMessage(parentRunId: string): Promise<string | null> {
  let host: string;
  let token: string;
  try {
    host = getEnvOrThrow("DATABRICKS_HOST");
    token = getEnvOrThrow("DATABRICKS_TOKEN");
  } catch {
    return null;
  }

  if (!host.startsWith("http://") && !host.startsWith("https://")) {
    host = `https://${host}`;
  }
  host = host.replace(/\/$/, "");

  try {
    const runRes = await fetch(`${host}/api/2.1/jobs/runs/get?run_id=${parentRunId}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!runRes.ok) return null;
    const runData = (await runRes.json()) as { tasks?: Array<{ run_id?: number | string }> };
    const taskRunId = runData.tasks?.[0]?.run_id;
    if (taskRunId === undefined || taskRunId === null) return null;

    const outRes = await fetch(
      `${host}/api/2.1/jobs/runs/get-output?run_id=${taskRunId}`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    if (!outRes.ok) return null;
    const outData = (await outRes.json()) as {
      notebook_output?: { result?: string | null };
    };
    const result = outData.notebook_output?.result;
    return typeof result === "string" && result.trim().length > 0 ? result : null;
  } catch (err) {
    console.warn("Failed to fetch notebook exit message:", sanitizeDiagnosticMessage(err));
    return null;
  }
}

function sanitizeDiagnosticMessage(value: unknown): string {
  const message = value instanceof Error ? value.message : String(value);
  return message
    .replace(/https?:\/\/[A-Za-z0-9.-]+\.cloud\.databricks\.com/gi, "https://<databricks-workspace-host>")
    .replace(/\/sql\/1\.0\/warehouses\/[A-Za-z0-9-]+/gi, "/sql/1.0/warehouses/<warehouse-id>")
    .replace(/dapi[A-Za-z0-9]+/gi, "<databricks-token>")
    .replace(/Bearer\s+[A-Za-z0-9._~+/=-]+/gi, "Bearer <redacted>")
    .replace(/postgres(?:ql)?:\/\/[^\s"'`]+/gi, "<postgres-connection-url>");
}
