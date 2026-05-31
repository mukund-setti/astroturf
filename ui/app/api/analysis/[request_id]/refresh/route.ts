import { NextResponse } from "next/server";
import { getAnalysisRequest, updateAnalysisRequest } from "@/lib/analysis-store";
import { getPipelineOutputCounts } from "@/lib/databricks";
import { getNotebookExitMessage, getRunStatus } from "@/lib/databricks-jobs";

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
          // Only downgrade a SUCCESS run to failed when we can actually
          // confirm the lakehouse has zero rows for this docket. When
          // `getPipelineOutputCounts` returns null we could not verify
          // (mock mode, missing SQL warehouse env, or live query
          // failure); trust the Databricks SUCCESS in that case rather
          // than fabricating a zero-count failure.
          let counts: Awaited<ReturnType<typeof getPipelineOutputCounts>>;
          try {
            counts = await getPipelineOutputCounts(req.docket_id);
          } catch (countErr) {
            console.warn(
              `Failed to verify lakehouse counts for ${req.docket_id}; trusting Databricks SUCCESS.`,
              countErr,
            );
            counts = null;
          }
          if (counts === null) {
            newStatus = "succeeded";
            error_message = null;
          } else if (counts.raw_comments === 0 || counts.parsed_comments === 0) {
            newStatus = "failed";
            const exitMessage = await getNotebookExitMessage(databricks_run_id);
            const parts = [
              "Databricks run completed, but no reviewable comments were loaded for this docket.",
              `Raw rows: ${counts.raw_comments}; parsed rows: ${counts.parsed_comments}; export rows: ${counts.export_rows}; clusters: ${counts.export_clusters}.`,
            ];
            if (exitMessage && /dry[\s_-]?run/i.test(exitMessage)) {
              parts.push(
                `Notebook exited early with: "${exitMessage}". The workspace job is pinned to dry-run mode. Clear the 'dry_run=true' notebook task base_parameter in the Databricks job UI (or re-run; the UI now hard-pins dry_run=false in job_parameters).`,
              );
            } else if (exitMessage) {
              parts.push(`Notebook exit message: "${exitMessage}".`);
            } else {
              parts.push(
                "This usually means the docket ID/source pair did not resolve to public comments, the source API returned no usable records, the deployed notebook exited before ingestion (e.g. dry-run), or the UI catalog/data root does not match the catalog/data root the Databricks job actually wrote to (check DATABRICKS_CATALOG and DATABRICKS_DATA_ROOT).",
              );
            }
            error_message = parts.join(" ");
          } else {
            newStatus = "succeeded";
            error_message = null;
          }
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
