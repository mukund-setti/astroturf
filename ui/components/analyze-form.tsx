"use client";

import { useCallback, useMemo, useState } from "react";
import type { ChangeEvent } from "react";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import { estimateRuntime, formatRuntime } from "@/lib/runtime-estimate";

export interface DocketPreset {
  docketId: string;
  source: string;
  topicId: string;
  agencyId: string;
  title: string;
  expectedScale: string;
  notes: string;
  startDate?: string;
  endDate?: string;
}

interface AnalyzeFormProps {
  initial: DocketPreset;
  knownDockets: DocketPreset[];
  executionMode?: "command" | "local_process" | "databricks_job";
}

const SOURCE_OPTIONS = ["regulations_gov", "ecfs"] as const;

export function AnalyzeForm({ initial, knownDockets, executionMode = "command" }: AnalyzeFormProps) {
  const router = useRouter();

  const [docketId, setDocketId] = useState(initial.docketId || "");
  const [source, setSource] = useState(initial.source || "regulations_gov");
  const [topicId, setTopicId] = useState(initial.topicId || "");
  const [agencyId, setAgencyId] = useState(initial.agencyId || "");
  const [title, setTitle] = useState(initial.title || "");
  const [startDate, setStartDate] = useState(initial.startDate || "");
  const [endDate, setEndDate] = useState(initial.endDate || "");
  const [expectedScale, setExpectedScale] = useState(initial.expectedScale || "");
  const [notes, setNotes] = useState(
    initial.notes || "Registered from the Astroturf Analyze a docket workflow."
  );

  const [yamlCopied, setYamlCopied] = useState(false);
  const [commandsCopied, setCommandsCopied] = useState(false);

  // Background pipeline trigger states (local mode)
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitMessage, setSubmitMessage] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [limit, setLimit] = useState("100");
  const [lookupStatus, setLookupStatus] = useState<"idle" | "loading" | "found" | "not_found">("idle");

  const handlePresetChange = (event: ChangeEvent<HTMLSelectElement>) => {
    const selectedId = event.target.value;
    const found = knownDockets.find((d) => d.docketId === selectedId);
    if (found) {
      setDocketId(found.docketId);
      setSource(found.source || "regulations_gov");
      setTopicId(found.topicId);
      setAgencyId(found.agencyId);
      setTitle(found.title);
      setExpectedScale(found.expectedScale);
      setNotes(found.notes);
      setStartDate(found.startDate || "");
      setEndDate(found.endDate || "");
    }
  };

  const lookupDocket = useCallback(async (id?: string) => {
    const lookupId = (id ?? docketId).trim();
    if (!lookupId || lookupId.length < 3) return;
    setLookupStatus("loading");
    try {
      const res = await fetch("/api/docket-lookup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ docketId: lookupId }),
      });
      const data = await res.json();
      if (data.found) {
        setSource(data.source || source);
        setTopicId(data.topicId || topicId);
        setAgencyId(data.agencyId || agencyId);
        setTitle(data.title || title);
        setExpectedScale(data.expectedScale || expectedScale);
        if (data.summary && (!notes || notes === "Registered from the Astroturf Analyze a docket workflow.")) {
          setNotes(data.summary);
        }
        setLookupStatus("found");
      } else {
        setLookupStatus("not_found");
      }
    } catch {
      setLookupStatus("not_found");
    }
  }, [docketId, source, topicId, agencyId, title, expectedScale, notes]);

  const handleDocketIdBlur = useCallback(() => {
    const trimmed = docketId.trim();
    // Auto-lookup when the ID looks real: contains a hyphen or is 3+ digits
    if (trimmed.length >= 3 && (trimmed.includes("-") || /^\d{3,}$/.test(trimmed))) {
      lookupDocket(trimmed);
    }
  }, [docketId, lookupDocket]);

  const yamlSnippet = useMemo(() => {
    return [
      `- docket_id: "${docketId || "<DOCKET-ID>"}"`,
      `  source: "${source}"`,
      `  topic_id: "${topicId || "<topic_id>"}"`,
      `  agency_id: "${agencyId || "<AGENCY>"}"`,
      `  title: "${title || "<Rulemaking title>"}"`,
      `  date_window:`,
      `    start_date: ${formatYamlScalar(startDate)}`,
      `    end_date: ${formatYamlScalar(endDate)}`,
      `  ingestion_mode: "full"`,
      `  expected_scale: ${expectedScale || "<comment_count_estimate>"}`,
      `  processing_status: "configured_awaiting_run"`,
      `  notes: ${formatYamlString(notes)}`,
    ].join("\n");
  }, [
    docketId,
    source,
    topicId,
    agencyId,
    title,
    startDate,
    endDate,
    expectedScale,
    notes,
  ]);

  const commandSnippet = useMemo(() => {
    const id = docketId || "<DOCKET-ID>";
    return [
      `.uv-test-venv\\Scripts\\python.exe scripts\\run_ingestion.py --docket-id ${id}`,
      `.uv-test-venv\\Scripts\\python.exe scripts\\run_embedding.py --docket-id ${id} --backend databricks`,
      `.uv-test-venv\\Scripts\\python.exe scripts\\run_clustering.py --docket-id ${id} --clustering-mode vector_search`,
    ].join("\n");
  }, [docketId]);

  const isComplete = Boolean(docketId && topicId && agencyId);

  // Live ETA shown to the user as they tweak source / scale. The estimator
  // returns honest numbers based on observed regulations.gov / ECFS pipeline
  // rates. If the user hasn't entered a scale yet we fall back to 1000 just
  // to show the order-of-magnitude shape; the actual quoted number updates
  // the moment they type a real value.
  const etaScale = (() => {
    const n = Number(expectedScale);
    if (!isNaN(n) && n > 0) return Math.floor(n);
    return 1000;
  })();
  const etaSource =
    source === "regulations_gov" || source === "ecfs"
      ? (source as "regulations_gov" | "ecfs")
      : "regulations_gov";
  const etaEstimate = useMemo(
    () => estimateRuntime(etaSource, etaScale),
    [etaSource, etaScale],
  );

  async function copyToClipboard(
    text: string,
    setter: (value: boolean) => void,
  ) {
    try {
      if (typeof navigator !== "undefined" && navigator.clipboard) {
        await navigator.clipboard.writeText(text);
      } else {
        // Fallback for older browsers
        const ta = document.createElement("textarea");
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
      }
      setter(true);
      setTimeout(() => setter(false), 1500);
    } catch {
      setter(false);
    }
  }

  // Handle Local trigger POST (fallback/dev mode)
  async function handleRegisterAndRunLocal() {
    if (!isComplete) return;
    setIsSubmitting(true);
    setSubmitMessage(null);
    setSubmitError(null);

    try {
      const res = await fetch("/api/analyze/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          docketId,
          source,
          topicId,
          agencyId,
          title,
          startDate,
          endDate,
          expectedScale,
          notes,
          limit: limit || "0", // 0 or empty for full run
        }),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || "Failed to trigger local pipeline execution.");
      }

      setSubmitMessage(data.message);
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Unknown error occurred.");
    } finally {
      setIsSubmitting(false);
    }
  }

  // Handle Hosted submit POST (real Databricks cloud orchestration)
  async function handleRegisterAndRunHosted() {
    if (!isComplete) return;
    setIsSubmitting(true);
    setSubmitMessage(null);
    setSubmitError(null);

    try {
      const res = await fetch("/api/analysis", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          docketId,
          source,
          topicId,
          agencyId,
          title,
          startDate,
          endDate,
          expectedScale,
          notes,
        }),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || "Failed to submit analysis job to Databricks.");
      }

      // Redirect to the newly created analysis request page
      router.push(`/analysis/${data.request_id}`);
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Unknown error occurred.");
      setIsSubmitting(false);
    }
  }

  // Handle Command-only submit POST
  async function handleRegisterDocketOnly() {
    if (!isComplete) return;
    setIsSubmitting(true);
    setSubmitMessage(null);
    setSubmitError(null);

    try {
      const res = await fetch("/api/analysis", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          docketId,
          source,
          topicId,
          agencyId,
          title,
          startDate,
          endDate,
          expectedScale,
          notes,
        }),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || "Failed to register docket draft.");
      }

      // Redirect to request details so they can copy pipeline commands
      router.push(`/analysis/${data.request_id}`);
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Unknown error occurred.");
      setIsSubmitting(false);
    }
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[0.9fr_1.1fr] gap-8">
      <section className="bg-card border border-rule rounded-sm p-6">
        <h2 className="font-display text-2xl font-semibold mb-5">
          Docket registration
        </h2>

        {/* Quick-pick select wrapper */}
        <div className="mb-6 p-4 rounded-sm border border-brand/20 bg-brand/5">
          <span className="block text-[10px] font-sans uppercase tracking-[0.24em] text-brand font-semibold mb-2">
            Quick Autofill from Known Dockets
          </span>
          <label className="block">
            <span className="sr-only">Select a known docket</span>
            <select
              onChange={handlePresetChange}
              value={docketId && knownDockets.some((d) => d.docketId === docketId) ? docketId : ""}
              className="h-10 w-full rounded-sm border border-rule bg-background px-3 text-sm text-foreground outline-none focus:border-brand focus:ring-1 focus:ring-brand/30 cursor-pointer"
              suppressHydrationWarning
            >
              <option value="" disabled>-- Select a known docket --</option>
              {knownDockets.map((preset) => (
                <option key={preset.docketId} value={preset.docketId}>
                  {preset.docketId} - {preset.title} ({preset.agencyId})
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="space-y-4">
          <label className="block">
            <span className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-1">
              Docket ID
            </span>
            <div className="flex gap-2">
              <input
                type="text"
                value={docketId}
                onChange={(e) => {
                  setDocketId(e.target.value);
                  if (lookupStatus !== "idle") setLookupStatus("idle");
                }}
                onBlur={handleDocketIdBlur}
                placeholder="EPA-HQ-OAR-2021-0317 or 17-108"
                className="h-10 flex-1 rounded-sm border border-rule bg-background px-3 text-sm text-foreground placeholder:text-muted-foreground/70 outline-none focus:border-brand focus:ring-1 focus:ring-brand/30"
                suppressHydrationWarning
              />
              <button
                type="button"
                suppressHydrationWarning
                onClick={() => lookupDocket()}
                disabled={!docketId.trim() || lookupStatus === "loading"}
                className={cn(
                  "h-10 px-3 rounded-sm text-[10px] font-semibold uppercase tracking-wider transition-colors whitespace-nowrap",
                  lookupStatus === "loading"
                    ? "bg-secondary text-muted-foreground cursor-wait"
                    : lookupStatus === "found"
                    ? "bg-emerald-500/10 border border-emerald-500/20 text-emerald-500"
                    : docketId.trim()
                    ? "border border-brand/40 text-brand hover:bg-brand/5 cursor-pointer"
                    : "bg-secondary text-muted-foreground cursor-not-allowed"
                )}
              >
                {lookupStatus === "loading"
                  ? "Looking up…"
                  : lookupStatus === "found"
                  ? "✓ Found"
                  : "Lookup"}
              </button>
            </div>
            {lookupStatus === "found" && (
              <span className="block mt-1 text-[10px] text-emerald-500">
                Fields auto-filled from catalog.
              </span>
            )}
            {lookupStatus === "not_found" && (
              <span className="block mt-1 text-[10px] text-muted-foreground">
                Not in catalog — fill fields manually or submit to discover.
              </span>
            )}
          </label>
          <SelectField
            label="Source"
            value={source}
            onChange={setSource}
            options={SOURCE_OPTIONS}
          />
          <TextField
            label="Topic"
            value={topicId}
            onChange={setTopicId}
            placeholder="telecom, oil_and_gas, ai_regulation"
          />
          <TextField
            label="Agency"
            value={agencyId}
            onChange={setAgencyId}
            placeholder="FCC, EPA, FTC, CFPB, SEC"
          />
          <TextField
            label="Title"
            value={title}
            onChange={setTitle}
            placeholder="Short rulemaking title"
          />
          <div className="grid grid-cols-2 gap-3">
            <TextField
              label="Start date"
              value={startDate}
              onChange={setStartDate}
              placeholder="YYYY-MM-DD"
            />
            <TextField
              label="End date"
              value={endDate}
              onChange={setEndDate}
              placeholder="YYYY-MM-DD"
            />
          </div>
          <TextField
            label="Expected scale"
            value={expectedScale}
            onChange={setExpectedScale}
            placeholder="Estimated comment count (e.g. 15000)"
          />
          <TextField
            label="Notes"
            value={notes}
            onChange={setNotes}
            placeholder="Optional context for reviewers"
          />
        </div>

        {/* Honest runtime estimate shown before the user fires anything off,
            so they aren't surprised by a 4-hour wait after one click. The
            numbers come from ui/lib/runtime-estimate.ts which is calibrated
            against observed regulations.gov and ECFS pipeline rates. */}
        {isComplete && (
          <div className="mt-6 p-4 border border-rule rounded-sm bg-secondary/30 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-[10px] uppercase tracking-[0.24em] text-muted-foreground font-semibold">
                Estimated runtime
              </span>
              <span className="font-display text-lg font-semibold text-foreground">
                {formatRuntime(etaEstimate.totalMinutes)}
              </span>
            </div>
            <p className="text-[10px] leading-snug text-muted-foreground">
              {etaEstimate.bottleneckReason} Bottleneck stage:{" "}
              <strong className="text-foreground">{etaEstimate.bottleneckStage}</strong>.
            </p>
            <div className="grid grid-cols-6 gap-1 text-[9px] text-center font-mono">
              {(
                ["setup", "ingestion", "parsing", "embedding", "clustering", "export"] as const
              ).map((stage) => (
                <div key={stage} className="px-1 py-1 bg-background border border-rule rounded-sm">
                  <div className="text-muted-foreground uppercase tracking-wider mb-0.5">
                    {stage.slice(0, 4)}
                  </div>
                  <div className="text-foreground font-semibold">
                    {formatRuntime(etaEstimate.stageMinutes[stage])}
                  </div>
                </div>
              ))}
            </div>
            {etaEstimate.warnings.length > 0 && (
              <ul className="mt-2 space-y-1 text-[10px] text-amber-500 leading-snug">
                {etaEstimate.warnings.map((w, i) => (
                  <li key={i}>· {w}</li>
                ))}
              </ul>
            )}
          </div>
        )}

        {/* Execution Settings and Trigger buttons */}
        <div className="mt-6 pt-6 border-t border-rule space-y-4">
          <h3 className="font-sans text-[11px] uppercase tracking-wider text-foreground font-semibold">
            {executionMode === "databricks_job"
              ? "Orchestration Settings (Databricks Cloud)"
              : executionMode === "local_process"
              ? "Execution Settings (Local Developer)"
              : "Configuration Actions (Command-Generation)"}
          </h3>

          {executionMode === "local_process" && (
            <TextField
              label="Truncate processing limit (e.g. 100 for fast local run)"
              value={limit}
              onChange={setLimit}
              placeholder="No limit if empty"
            />
          )}

          {/* Mode-specific execution notices */}
          {executionMode === "command" && (
            <div className="p-3 bg-amber-500/5 border border-amber-500/10 text-amber-500 text-xs rounded-sm leading-relaxed">
              <span className="font-semibold block mb-0.5 text-[10px] uppercase tracking-wider">Command-Generation Mode Active</span>
              Local process spawning is disabled. Clicking below will register a draft docket request in the database and display offline shell commands.
            </div>
          )}
          {executionMode === "local_process" && (
            <div className="p-3 bg-blue-500/5 border border-blue-500/10 text-blue-500 text-xs rounded-sm leading-relaxed">
              <span className="font-semibold block mb-0.5 text-[10px] uppercase tracking-wider">Local Developer Execution Mode Active</span>
              Opt-in only. Clicking below appends configs directly to YAML and spawns background Python threads on your workspace machine.
            </div>
          )}
          {executionMode === "databricks_job" && (
            <div className="p-3 bg-green-500/5 border border-green-500/10 text-green-500 text-xs rounded-sm leading-relaxed">
              <span className="font-semibold block mb-0.5 text-[10px] uppercase tracking-wider">Databricks Jobs Mode Active</span>
              Production-safe. Submits docket analysis pipelines directly to your serverless hosted Databricks instance.
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {executionMode === "databricks_job" ? (
              <button
                type="button"
                suppressHydrationWarning
                onClick={handleRegisterAndRunHosted}
                disabled={!isComplete || isSubmitting}
                className={
                  "inline-flex h-10 items-center justify-center rounded-sm px-4 text-xs font-semibold uppercase tracking-wider transition-colors " +
                  (isComplete && !isSubmitting
                    ? "bg-brand text-white hover:bg-brand/90 cursor-pointer"
                    : "bg-secondary text-muted-foreground cursor-not-allowed")
                }
              >
                {isSubmitting ? "Submitting Job..." : "Submit Analysis Job"}
              </button>
            ) : executionMode === "local_process" ? (
              <button
                type="button"
                suppressHydrationWarning
                onClick={handleRegisterAndRunLocal}
                disabled={!isComplete || isSubmitting}
                className={
                  "inline-flex h-10 items-center justify-center rounded-sm px-4 text-xs font-semibold uppercase tracking-wider transition-colors " +
                  (isComplete && !isSubmitting
                    ? "bg-brand text-white hover:bg-brand/90 cursor-pointer"
                    : "bg-secondary text-muted-foreground cursor-not-allowed")
                }
              >
                {isSubmitting ? "Running Ingestion..." : "Register & Run Pipeline"}
              </button>
            ) : (
              <button
                type="button"
                suppressHydrationWarning
                onClick={handleRegisterDocketOnly}
                disabled={!isComplete || isSubmitting}
                className={
                  "inline-flex h-10 items-center justify-center rounded-sm px-4 text-xs font-semibold uppercase tracking-wider transition-colors " +
                  (isComplete && !isSubmitting
                    ? "bg-brand text-white hover:bg-brand/90 cursor-pointer"
                    : "bg-secondary text-muted-foreground cursor-not-allowed")
                }
              >
                {isSubmitting ? "Registering..." : "Register Docket Draft"}
              </button>
            )}

            <button
              type="button"
              suppressHydrationWarning
              onClick={() => copyToClipboard(yamlSnippet, setYamlCopied)}
              disabled={!isComplete}
              className={
                "inline-flex h-10 items-center justify-center rounded-sm px-4 text-xs font-semibold uppercase tracking-wider transition-colors " +
                (isComplete
                  ? "border border-brand/40 text-brand hover:bg-brand/5 cursor-pointer"
                  : "border border-rule text-muted-foreground cursor-not-allowed")
              }
            >
              {yamlCopied ? "Config copied" : "Copy pipeline config"}
            </button>
          </div>

          {/* Feedback messages (Local mode) */}
          {executionMode === "local_process" && submitMessage && (
            <div className="p-3 bg-emerald-500/10 border border-emerald-500/20 text-emerald-500 text-xs rounded-sm">
              <span className="font-semibold block mb-1">Success!</span>
              {submitMessage}
              <div className="mt-1.5 font-mono text-[10px] text-emerald-500/70 border-t border-emerald-500/10 pt-1.5">
                Logs will stream to:
                <code className="block mt-1 font-mono text-[9px] bg-emerald-950/20 p-1 rounded-sm text-emerald-300">
                  data/logs/pipeline-{docketId}.log
                </code>
              </div>
            </div>
          )}

          {submitError && (
            <div className="p-3 bg-destructive/10 border border-destructive/20 text-destructive text-xs rounded-sm">
              <span className="font-semibold block mb-1">Execution Error</span>
              {submitError}
            </div>
          )}
        </div>

        <p className="mt-4 text-[11px] text-muted-foreground leading-relaxed font-sans">
          {executionMode === "databricks_job" ? (
            <span>
              Tip: <strong>Submit Analysis Job</strong> sends a pipeline trigger command directly to your hosted Databricks instance and navigates to the tracking dashboard to monitor progress.
            </span>
          ) : executionMode === "local_process" ? (
            <span>
              Tip: <strong>Register & Run Pipeline</strong> appends the new entry directly to your local
              <code className="font-mono mx-1">configs/dockets.yaml</code> and starts the complete
              unified orchestration pipeline runner (ingest, parse, embed, cluster, and export) in the background.
            </span>
          ) : (
            <span>
              Tip: <strong>Register Docket Draft</strong> creates a tracking request in the database and navigates to the details page where you can copy CLI commands to run execution offline in your terminal.
            </span>
          )}
        </p>
      </section>

      <section className="space-y-6">
        <div className="bg-card border border-rule rounded-sm p-6">
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-display text-2xl font-semibold">
              configs/dockets.yaml snippet
            </h2>
            <button
              type="button"
              suppressHydrationWarning
              onClick={() => copyToClipboard(yamlSnippet, setYamlCopied)}
              className="text-[10px] uppercase tracking-wider bg-secondary text-foreground/80 px-2 py-1 rounded-sm hover:bg-muted transition-colors cursor-pointer"
            >
              {yamlCopied ? "Copied" : "Copy"}
            </button>
          </div>
          <pre className="overflow-x-auto whitespace-pre rounded-sm bg-background border border-rule p-4 text-[11px] leading-relaxed text-foreground">
            {yamlSnippet}
          </pre>
        </div>

        <div className="bg-card border border-rule rounded-sm p-6">
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-display text-2xl font-semibold">
              Pipeline commands
            </h2>
            <button
              type="button"
              suppressHydrationWarning
              onClick={() => copyToClipboard(commandSnippet, setCommandsCopied)}
              className="text-[10px] uppercase tracking-wider bg-secondary text-foreground/80 px-2 py-1 rounded-sm hover:bg-muted transition-colors cursor-pointer"
            >
              {commandsCopied ? "Copied" : "Copy"}
            </button>
          </div>
          <pre className="overflow-x-auto whitespace-pre rounded-sm bg-background border border-rule p-4 text-[11px] leading-relaxed text-foreground">
            {commandSnippet}
          </pre>
          <p className="mt-3 text-[11px] text-muted-foreground leading-relaxed">
            For production-scale runs, use the Databricks workflow task order
            from the end-to-end runbook: load sample tables, embed, cluster,
            export dashboard data.
          </p>
        </div>
      </section>
    </div>
  );
}

function TextField({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (next: string) => void;
  placeholder: string;
}) {
  const handleChange = (event: ChangeEvent<HTMLInputElement>) => {
    onChange(event.target.value);
  };
  return (
    <label className="block">
      <span className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-1">
        {label}
      </span>
      <input
        type="text"
        value={value}
        onChange={handleChange}
        placeholder={placeholder}
        className="h-10 w-full rounded-sm border border-rule bg-background px-3 text-sm text-foreground placeholder:text-muted-foreground/70 outline-none focus:border-brand focus:ring-1 focus:ring-brand/30"
        suppressHydrationWarning
      />
    </label>
  );
}

function SelectField({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (next: string) => void;
  options: readonly string[];
}) {
  const handleChange = (event: ChangeEvent<HTMLSelectElement>) => {
    onChange(event.target.value);
  };
  return (
    <label className="block">
      <span className="block text-[10px] uppercase tracking-wider text-muted-foreground mb-1">
        {label}
      </span>
      <select
        value={value}
        onChange={handleChange}
        className="h-10 w-full rounded-sm border border-rule bg-background px-3 text-sm text-foreground outline-none focus:border-brand focus:ring-1 focus:ring-brand/30"
        suppressHydrationWarning
      >
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </label>
  );
}

function formatYamlScalar(value: string): string {
  // YAML `null` for empty dates, otherwise emit quoted ISO strings.
  if (!value || !value.trim()) return "null";
  const trimmed = value.trim();
  return `"${trimmed.replace(/"/g, '\\"')}"`;
}

function formatYamlString(value: string): string {
  // Always quote strings for safety; escape embedded quotes.
  return `"${(value ?? "").replace(/"/g, '\\"')}"`;
}
