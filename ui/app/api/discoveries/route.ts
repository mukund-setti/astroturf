import { NextResponse } from "next/server";
import { listDiscoveredDockets, incrementUserRequestCount } from "@/lib/docket-catalog";
import { spawn } from "child_process";
import path from "path";

export async function GET() {
  try {
    const dockets = await listDiscoveredDockets();
    return NextResponse.json(dockets);
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}

import { getExecutionMode, validateExecutionModeServer } from "@/lib/execution-mode";

export async function POST(request: Request) {
  try {
    // Enforce production server process-spawning safety checks
    validateExecutionModeServer();

    const mode = getExecutionMode();
    const body = await request.json();
    const { action, docketId } = body;

    if (action === "trigger") {
      if (mode === "local_process") {
        triggerAutopilotRunInBackground();
        return NextResponse.json({ success: true, message: "Triggered Autopilot run sweep successfully in local background." });
      }
      
      if (mode === "databricks_job") {
        // In Databricks Jobs mode, a scheduled workspace job runs the Autopilot workflow.
        // If a custom autopilot job ID is defined, we can trigger it, otherwise we report success for queueing.
        const autopilotJobId = process.env.DATABRICKS_AUTOPILOT_JOB_ID;
        if (autopilotJobId) {
          try {
            await submitDatabricksAutopilotJob(autopilotJobId);
            return NextResponse.json({ success: true, message: "Triggered Databricks Autopilot Workflow run successfully." });
          } catch (dbErr) {
            console.error("Failed to submit Autopilot Databricks Job:", dbErr);
            return NextResponse.json({ error: `Failed to submit Databricks Autopilot Job: ${dbErr instanceof Error ? dbErr.message : "Unknown error"}` }, { status: 500 });
          }
        }
        return NextResponse.json({ success: true, message: "Autopilot sweep queued in cloud catalog (Databricks scheduled workflow will process)." });
      }

      // Command mode
      return NextResponse.json({ success: true, message: "Command-generation mode active. Trigger sweep offline using scripts/run_autopilot.py" });
    }

    if (!docketId) {
      return NextResponse.json({ error: "Missing required docketId" }, { status: 400 });
    }

    if (action === "request") {
      const updated = await incrementUserRequestCount(docketId);
      if (!updated) {
        return NextResponse.json({ error: "Docket not found in catalog" }, { status: 404 });
      }

      // Automatically trigger Autopilot priority run when requested, but ONLY if we are in local_process mode
      if (mode === "local_process") {
        triggerAutopilotRunInBackground();
      } else if (mode === "databricks_job") {
        const autopilotJobId = process.env.DATABRICKS_AUTOPILOT_JOB_ID;
        if (autopilotJobId) {
          try {
            await submitDatabricksAutopilotJob(autopilotJobId);
          } catch (dbErr) {
            console.error("Auto-trigger Databricks Autopilot failed:", dbErr);
          }
        }
      }

      return NextResponse.json({ success: true, docket: updated });
    }

    return NextResponse.json({ error: "Unsupported action type" }, { status: 400 });
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}

/**
 * Submits a Databricks Job run for the Autopilot crawler/classification task
 */
async function submitDatabricksAutopilotJob(jobId: string): Promise<void> {
  let host = process.env.DATABRICKS_HOST;
  const token = process.env.DATABRICKS_TOKEN;

  if (!host || !token) {
    throw new Error("Missing DATABRICKS_HOST or DATABRICKS_TOKEN environment variables.");
  }

  if (!host.startsWith("http://") && !host.startsWith("https://")) {
    host = `https://${host}`;
  }
  host = host.replace(/\/$/, "");

  const url = `${host}/api/2.1/jobs/run-now`;
  const payload = {
    job_id: parseInt(jobId, 10),
  };

  const res = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Databricks API returned HTTP ${res.status}: ${errText}`);
  }
}

function triggerAutopilotRunInBackground() {
  try {
    const pythonPath = path.resolve(process.cwd(), "..", ".uv-test-venv", "Scripts", "python.exe");
    const scriptPath = path.resolve(process.cwd(), "..", "scripts", "run_autopilot.py");
    
    // Spawns Autopilot in background to classify and calculate scores
    const child = spawn(pythonPath, [scriptPath, "--trigger-jobs"], {
      detached: true,
      stdio: "ignore",
      cwd: path.resolve(process.cwd(), ".."),
    });
    child.unref();
    console.log("Triggered Autopilot classification run in background.");
  } catch (err) {
    console.error("Failed to run Autopilot background process:", err);
  }
}
