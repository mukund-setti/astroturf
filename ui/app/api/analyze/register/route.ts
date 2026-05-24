import { NextResponse } from "next/server";
import fs from "fs";
import path from "path";
import { spawn } from "child_process";

import { getExecutionMode, validateExecutionModeServer } from "@/lib/execution-mode";

export async function POST(request: Request) {
  try {
    // Enforce production server process-spawning safety checks
    validateExecutionModeServer();

    const mode = getExecutionMode();
    if (mode !== "local_process") {
      return NextResponse.json(
        { error: "/api/analyze/register is only supported in local_process mode." },
        { status: 400 }
      );
    }
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
      limit = "100", // Default limit to run relatively fast
    } = body;

    if (!docketId || !source || !topicId || !agencyId) {
      return NextResponse.json(
        { error: "Missing required fields: docketId, source, topicId, agencyId" },
        { status: 400 }
      );
    }

    const docketsYamlPath = path.resolve(process.cwd(), "..", "configs", "dockets.yaml");
    if (!fs.existsSync(docketsYamlPath)) {
      return NextResponse.json(
        { error: `Dockets config file not found at ${docketsYamlPath}` },
        { status: 500 }
      );
    }

    let existingContent = fs.readFileSync(docketsYamlPath, "utf8");

    // Standardized check for existing docket_id in dockets.yaml
    const docketExistsRegex = new RegExp(`docket_id:\\s*['"]?${escapeRegex(docketId)}['"]?\\s*(\\n|$)`, "i");
    const exists = docketExistsRegex.test(existingContent);

    if (!exists) {
      // Append the new docket configuration to configs/dockets.yaml
      const formattedStartDate = startDate && startDate.trim() ? `"${startDate.trim()}"` : "null";
      const formattedEndDate = endDate && endDate.trim() ? `"${endDate.trim()}"` : "null";
      const formattedExpectedScale = expectedScale && !isNaN(Number(expectedScale)) ? Number(expectedScale) : 1000;
      const cleanNotes = (notes || "Registered from the Astroturf Analyze a docket workflow.").replace(/"/g, '\\"');
      const cleanTitle = (title || "Short rulemaking title").replace(/"/g, '\\"');

      const yamlBlock = `
- docket_id: "${docketId}"
  source: "${source}"
  topic_id: "${topicId}"
  agency_id: "${agencyId}"
  title: "${cleanTitle}"
  date_window:
    start_date: ${formattedStartDate}
    end_date: ${formattedEndDate}
  ingestion_mode: "full"
  expected_scale: ${formattedExpectedScale}
  processing_status: "configured_awaiting_run"
  notes: "${cleanNotes}"
`;
      // Ensure there's a trailing newline, and append
      if (!existingContent.endsWith("\n")) {
        existingContent += "\n";
      }
      fs.writeFileSync(docketsYamlPath, existingContent + yamlBlock, "utf8");
    }

    // Trigger local pipeline execution in the background
    const pythonPath = path.resolve(process.cwd(), "..", ".uv-test-venv", "Scripts", "python.exe");
    const scriptPath = path.resolve(process.cwd(), "..", "scripts", "run_docket_pipeline.py");
    const logDir = path.resolve(process.cwd(), "..", "data", "logs");

    if (!fs.existsSync(logDir)) {
      fs.mkdirSync(logDir, { recursive: true });
    }

    const logFile = path.join(logDir, `pipeline-${docketId}.log`);
    const out = fs.openSync(logFile, "w"); // "w" to overwrite or start fresh

    // Spawn pipeline in background with python scripts/run_docket_pipeline.py
    const args = [
      scriptPath,
      "--docket-id",
      docketId,
      "--mode",
      "local",
      "--stages",
      "ingest,parse,embed,cluster,export",
    ];

    if (limit && Number(limit) > 0) {
      args.push("--limit", limit);
    }

    const child = spawn(pythonPath, args, {
      detached: true,
      stdio: ["ignore", out, out],
      cwd: path.resolve(process.cwd(), ".."),
      env: { ...process.env, PYTHONUNBUFFERED: "1" },
    });

    child.unref();

    return NextResponse.json({
      success: true,
      message: exists
        ? "Docket already exists in config. Triggered pipeline run in background."
        : "Docket registered successfully in configs/dockets.yaml and triggered pipeline run in background.",
      logPath: `data/logs/pipeline-${docketId}.log`,
      docketId,
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

function escapeRegex(string: string) {
  return string.replace(/[-\/\\^$*+?.()|[\]{}]/g, "\\$&");
}
