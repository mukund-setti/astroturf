import { NextResponse } from "next/server";
import { getAnalysisRequest, updateAnalysisRequest } from "@/lib/analysis-store";
import {
  getDetailedStageCounts,
  type DetailedStageCounts,
} from "@/lib/databricks";
import {
  getNotebookExitMessage,
  getRunStatus,
} from "@/lib/databricks-jobs";

interface Context {
  params: Promise<{
    request_id: string;
  }>;
}

const TERMINAL_STATUSES = new Set(["succeeded", "failed", "canceled"]);

/**
 * Pollable, idempotent snapshot of an analysis request's progress.
 *
 * GET is safe to call on a short interval (e.g. every 10s from a client
 * component) because:
 *  - It never blocks on long Databricks calls.
 *  - It only writes back to the analysis store when the lifecycle state
 *     actually transitions (e.g. RUNNING -> SUCCESS). Repeated polls during
 *     the same state cause zero writes.
 *  - SQL stage counts are read in parallel and individual failures don't
 *     poison the whole response (see getDetailedStageCounts).
 *
 * Response shape is intentionally flat and JSON-stable so the client can
 * diff it cheaply.
 */
export async function GET(request: Request, { params }: Context) {
  try {
    const { request_id } = await params;
    const req = await getAnalysisRequest(request_id);
    if (!req) {
      return NextResponse.json(
        { error: `Analysis request with ID ${request_id} not found.` },
        { status: 404 },
      );
    }

    let currentStatus = req.status;
    let currentErrorMessage = req.error_message;

    // Refresh Databricks state only if the request is still in flight. Once
    // we've hit a terminal status, the row counts are the only thing worth
    // re-checking, and we want polling to be cheap.
    if (req.databricks_run_id && !TERMINAL_STATUSES.has(req.status)) {
      try {
        const runData = await getRunStatus(req.databricks_run_id);
        const lifeCycle = runData.state?.life_cycle_state;
        const result = runData.state?.result_state;
        const message = runData.state?.state_message || null;

        let nextStatus: typeof req.status = req.status;
        let nextError: string | null = req.error_message;

        if (lifeCycle === "PENDING") {
          nextStatus = "submitted";
        } else if (lifeCycle === "RUNNING" || lifeCycle === "TERMINATING") {
          nextStatus = "running";
        } else if (lifeCycle === "TERMINATED") {
          if (result === "SUCCESS") {
            // Don't trust SUCCESS yet - verify rows actually exist. The
            // older deployed notebook silently reports SUCCESS for zero-row
            // dockets; this is the choke point that catches it.
            const counts = await getDetailedStageCounts(req.docket_id);
            if (counts && (counts.raw_comments <= 0 || counts.parsed_comments <= 0)) {
              nextStatus = "failed";
              const exitMessage = await getNotebookExitMessage(req.databricks_run_id);
              const parts = [
                "Databricks run completed but produced no reviewable comments for this docket.",
                `bronze=${counts.raw_comments} parsed=${counts.parsed_comments} embeddings=${counts.comment_embeddings} clusters=${counts.clusters} export=${counts.export_rows}.`,
              ];
              if (exitMessage && /dry[\s_-]?run/i.test(exitMessage)) {
                parts.push(
                  `Notebook exited early: "${exitMessage}". Clear dry_run=true from the workspace job's task base_parameters.`,
                );
              } else if (exitMessage) {
                parts.push(`Notebook exit: "${exitMessage}".`);
              } else {
                parts.push(
                  "Common cause: docket ID + source pair has no public comments, or the source API returned nothing.",
                );
              }
              nextError = parts.join(" ");
            } else {
              nextStatus = "succeeded";
              nextError = null;
            }
          } else if (result === "FAILED" || result === "TIMEDOUT") {
            nextStatus = "failed";
            nextError = message || `Databricks run terminated: ${result}`;
          } else if (result === "CANCELED") {
            nextStatus = "canceled";
            nextError = "Databricks run was canceled.";
          } else {
            nextStatus = "failed";
            nextError = `Unknown Databricks result state: ${result}`;
          }
        } else if (lifeCycle === "SKIPPED") {
          nextStatus = "canceled";
          nextError = "Databricks run was skipped.";
        } else if (lifeCycle === "INTERNAL_ERROR") {
          nextStatus = "failed";
          nextError = message || "Databricks internal scheduler error.";
        }

        if (nextStatus !== req.status || nextError !== req.error_message) {
          await updateAnalysisRequest(request_id, {
            status: nextStatus,
            error_message: nextError,
          });
          currentStatus = nextStatus;
          currentErrorMessage = nextError;
        }
      } catch (dbErr) {
        // Polling should never blow up; log and return what we have.
        console.warn(
          `progress: failed to refresh Databricks state for ${req.databricks_run_id}`,
          dbErr,
        );
      }
    }

    let counts: DetailedStageCounts | null = null;
    try {
      counts = await getDetailedStageCounts(req.docket_id);
    } catch (countsErr) {
      console.warn(`progress: stage counts unavailable for ${req.docket_id}`, countsErr);
    }

    const elapsedMs = Date.now() - new Date(req.created_at).getTime();

    return NextResponse.json({
      request_id: req.request_id,
      docket_id: req.docket_id,
      source: req.source,
      expected_scale: req.expected_scale,
      status: currentStatus,
      error_message: currentErrorMessage,
      databricks_run_id: req.databricks_run_id,
      result_url: req.result_url,
      created_at: req.created_at,
      elapsed_ms: elapsedMs,
      counts,
      // Tell the client whether to keep polling. We stop polling on terminal
      // statuses; if the run is in flight but counts unavailable (e.g. mock
      // mode), the client should still poll in case Databricks state changes.
      is_terminal: TERMINAL_STATUSES.has(currentStatus),
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
