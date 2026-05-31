import { NextResponse } from "next/server";
import {
  createAnalysisRequest,
  listAnalysisRequests,
} from "@/lib/analysis-store";
import { submitDocketJob } from "@/lib/databricks-jobs";
import { getExecutionMode, validateExecutionModeServer } from "@/lib/execution-mode";
import { spawn } from "child_process";
import fs from "fs";
import path from "path";

export async function GET() {
  try {
    const list = await listAnalysisRequests();
    // Sort newest first
    list.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
    return NextResponse.json(list);
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

export async function POST(request: Request) {
  try {
    // 1. Enforce production server process spawning safety check
    validateExecutionModeServer();

    const mode = getExecutionMode();
    const body = await request.json();
    const {
      docketId,
      source,
      topicId,
      agencyId,
      title,
      startDate,
      endDate,
      expectedScale,
      notes,
      limit = "100", // local_process fallback limit
    } = body;

    // Validate inputs
    if (!docketId || !docketId.trim()) {
      return NextResponse.json({ error: "Missing required field: docketId" }, { status: 400 });
    }
    if (!source || !["regulations_gov", "ecfs"].includes(source)) {
      return NextResponse.json({ error: "Invalid or missing source: must be 'regulations_gov' or 'ecfs'" }, { status: 400 });
    }
    if (!topicId || !topicId.trim()) {
      return NextResponse.json({ error: "Missing required field: topicId" }, { status: 400 });
    }
    if (!agencyId || !agencyId.trim()) {
      return NextResponse.json({ error: "Missing required field: agencyId" }, { status: 400 });
    }

    // Trust the user's requested scale (no hard cap). The /analyze form and
    // /discoveries one-click confirmation surface an honest ETA up front via
    // ui/lib/runtime-estimate.ts, so users opt in to long runs eyes-open.
    // We only enforce that scale is a positive integer.
    const scaleNum = Math.max(
      1,
      Math.floor(
        expectedScale && !isNaN(Number(expectedScale)) ? Number(expectedScale) : 1000,
      ),
    );

    // Annotate the request with the ETA we computed at submission time so the
    // request detail page can show "you were quoted ~Xh, run has been going Yh"
    // honestly, without recomputing in case the cost model changes later.
    const { estimateRuntime, formatRuntime } = await import("@/lib/runtime-estimate");
    const eta = estimateRuntime(source as "regulations_gov" | "ecfs", scaleNum);
    const etaNote = ` (estimated runtime at submission: ${formatRuntime(eta.totalMinutes)}; bottleneck: ${eta.bottleneckStage})`;

    // Create a base draft request in local/UC store
    const newRequest = await createAnalysisRequest({
      docket_id: docketId.trim(),
      source,
      topic_id: topicId.trim(),
      agency_id: agencyId.trim(),
      title: (title || `Analysis request for ${docketId}`).trim(),
      date_start: startDate && startDate.trim() ? startDate.trim() : null,
      date_end: endDate && endDate.trim() ? endDate.trim() : null,
      expected_scale: scaleNum,
      notes:
        (notes || "Registered from the Astroturf Analyze a docket workflow.").trim() +
        etaNote,
    });

    // 2. Branch dynamically based on execution mode
    if (mode === "databricks_job") {
      try {
        const { run_id } = await submitDocketJob(newRequest);
        const { updateAnalysisRequest } = await import("@/lib/analysis-store");
        const finalReq = await updateAnalysisRequest(newRequest.request_id, {
          status: "submitted",
          databricks_run_id: run_id,
        });
        return NextResponse.json(finalReq);
      } catch (dbErr) {
        console.error("Databricks pipeline trigger failed for analysis request:", dbErr);
        const { updateAnalysisRequest } = await import("@/lib/analysis-store");
        const failedReq = await updateAnalysisRequest(newRequest.request_id, {
          status: "failed",
          error_message: dbErr instanceof Error ? dbErr.message : "Databricks Jobs API execution error.",
        });
        return NextResponse.json(failedReq);
      }
    }

    if (mode === "local_process") {
      try {
        // Register in configs/dockets.yaml if not present
        const docketsYamlPath = path.resolve(process.cwd(), "..", "configs", "dockets.yaml");
        if (fs.existsSync(docketsYamlPath)) {
          let existingContent = fs.readFileSync(docketsYamlPath, "utf8");
          const docketExistsRegex = new RegExp(`docket_id:\\s*['"]?${escapeRegex(docketId.trim())}['"]?\\s*(\\n|$)`, "i");
          
          if (!docketExistsRegex.test(existingContent)) {
            const formattedStartDate = startDate && startDate.trim() ? `"${startDate.trim()}"` : "null";
            const formattedEndDate = endDate && endDate.trim() ? `"${endDate.trim()}"` : "null";
            const cleanNotes = (notes || "Registered from local workflow.").replace(/"/g, '\\"');
            const cleanTitle = (title || "Ruled docket").replace(/"/g, '\\"');

            const yamlBlock = `
- docket_id: "${docketId.trim()}"
  source: "${source}"
  topic_id: "${topicId.trim()}"
  agency_id: "${agencyId.trim()}"
  title: "${cleanTitle}"
  date_window:
    start_date: ${formattedStartDate}
    end_date: ${formattedEndDate}
  ingestion_mode: "full"
  expected_scale: ${scaleNum}
  processing_status: "configured_awaiting_run"
  notes: "${cleanNotes}"
`;
            if (!existingContent.endsWith("\n")) {
              existingContent += "\n";
            }
            fs.writeFileSync(docketsYamlPath, existingContent + yamlBlock, "utf8");
          }
        }

        // Spawn Python local background process
        const pythonPath = path.resolve(process.cwd(), "..", ".uv-test-venv", "Scripts", "python.exe");
        const scriptPath = path.resolve(process.cwd(), "..", "scripts", "run_docket_pipeline.py");
        const logDir = path.resolve(process.cwd(), "..", "data", "logs");

        if (!fs.existsSync(logDir)) {
          fs.mkdirSync(logDir, { recursive: true });
        }

        const logFile = path.join(logDir, `pipeline-${docketId.trim()}.log`);
        const out = fs.openSync(logFile, "w");

        const args = [
          scriptPath,
          "--docket-id",
          docketId.trim(),
          "--mode",
          "local",
          "--stages",
          "ingest,parse,embed,cluster,export",
        ];

        if (limit && Number(limit) > 0) {
          args.push("--limit", String(limit));
        }

        const child = spawn(pythonPath, args, {
          detached: true,
          stdio: ["ignore", out, out],
          cwd: path.resolve(process.cwd(), ".."),
          env: { ...process.env, PYTHONUNBUFFERED: "1" },
        });
        child.unref();

        // Update draft request to running status for tracking
        const { updateAnalysisRequest } = await import("@/lib/analysis-store");
        const runningReq = await updateAnalysisRequest(newRequest.request_id, {
          status: "running",
          notes: `${newRequest.notes} (Local developer execution triggered).`,
        });

        return NextResponse.json(runningReq);
      } catch (localErr) {
        console.error("Local process trigger failed for analysis request:", localErr);
        const { updateAnalysisRequest } = await import("@/lib/analysis-store");
        const failedReq = await updateAnalysisRequest(newRequest.request_id, {
          status: "failed",
          error_message: localErr instanceof Error ? localErr.message : "Local pipeline spawn error.",
        });
        return NextResponse.json(failedReq);
      }
    }

    // Default to "command" mode: just return the draft request record
    return NextResponse.json(newRequest);
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

function escapeRegex(string: string) {
  return string.replace(/[-\/\\^$*+?.()|[\]{}]/g, "\\$&");
}
