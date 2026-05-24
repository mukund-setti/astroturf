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

  const payload = {
    job_id: parseInt(jobId, 10),
    notebook_params: {
      docket_id: request.docket_id,
      source: request.source,
      topic_id: request.topic_id,
      agency_id: request.agency_id,
      start_date: request.date_start || "null",
      end_date: request.date_end || "null",
      expected_scale: String(request.expected_scale),
      request_id: request.request_id,
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
        throw new Error(`Databricks Job with ID ${jobId} was not found on host ${host}.`);
      }
      const errText = await res.text();
      throw new Error(`Databricks API returned HTTP ${res.status}: ${errText}`);
    }

    const data = await res.json();
    if (!data.run_id) {
      throw new Error("Databricks API run-now did not return a valid run_id.");
    }

    return { run_id: String(data.run_id) };
  } catch (err) {
    console.error("Databricks job submission failed:", err);
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
      throw new Error(`Databricks API returned HTTP ${res.status}: ${errText}`);
    }

    const data = await res.json();
    return data as DatabricksRunResponse;
  } catch (err) {
    console.error(`Failed to fetch Databricks run status for runId ${runId}:`, err);
    throw err;
  }
}
