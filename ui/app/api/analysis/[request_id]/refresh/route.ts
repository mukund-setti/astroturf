import { NextResponse } from "next/server";
import { getAnalysisRequest, updateAnalysisRequest } from "@/lib/analysis-store";
import { getRunStatus } from "@/lib/databricks-jobs";

interface Context {
  params: Promise<{
    request_id: string;
  }>;
}

export async function POST(request: Request, { params }: Context) {
  try {
    const { request_id } = await params;
    const req = await getAnalysisRequest(request_id);
    if (!req) {
      return NextResponse.json({ error: `Analysis request with ID ${request_id} not found.` }, { status: 404 });
    }

    const { databricks_run_id } = req;
    if (!databricks_run_id) {
      // No databricks_run_id to refresh; return as is (could be a local fallback run)
      return NextResponse.json(req);
    }

    try {
      const runData = await getRunStatus(databricks_run_id);
      
      const lifeCycle = runData.state?.life_cycle_state;
      const result = runData.state?.result_state;
      const message = runData.state?.state_message || null;

      let newStatus: typeof req.status = req.status;
      let error_message: string | null = req.error_message;

      if (lifeCycle === "PENDING") {
        newStatus = "submitted";
      } else if (lifeCycle === "RUNNING" || lifeCycle === "TERMINATING") {
        newStatus = "running";
      } else if (lifeCycle === "TERMINATED") {
        if (result === "SUCCESS") {
          newStatus = "succeeded";
          error_message = null;
        } else if (result === "FAILED" || result === "TIMEDOUT") {
          newStatus = "failed";
          error_message = message || `Databricks Run terminated with status: ${result}`;
        } else if (result === "CANCELED") {
          newStatus = "canceled";
          error_message = "Databricks Run was canceled by user.";
        } else {
          newStatus = "failed";
          error_message = `Unknown Databricks result state: ${result}`;
        }
      } else if (lifeCycle === "SKIPPED") {
        newStatus = "canceled";
        error_message = "Databricks Run was skipped.";
      } else if (lifeCycle === "INTERNAL_ERROR") {
        newStatus = "failed";
        error_message = message || "Databricks internal scheduler error occurred.";
      }

      const updated = await updateAnalysisRequest(request_id, {
        status: newStatus,
        error_message: error_message,
        // Optional link to run in Databricks workspace
        result_url: req.result_url || (process.env.DATABRICKS_HOST 
          ? `${process.env.DATABRICKS_HOST.replace(/\/$/, "")}/#job/run/${databricks_run_id}` 
          : null),
      });

      return NextResponse.json(updated);
    } catch (dbErr) {
      console.error(`Failed to refresh Databricks run status for run_id ${databricks_run_id}:`, dbErr);
      // Update with refresh fetch error message but don't fail HTTP request entirely
      const updated = await updateAnalysisRequest(request_id, {
        error_message: `Refresh failed: ${dbErr instanceof Error ? dbErr.message : "Unknown API connectivity issue."}`,
      });
      return NextResponse.json(updated);
    }
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
