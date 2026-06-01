export function ScaleFailureCard() {
  const scalingData = [
    { n: "1,000", ram: "4 MB", status: "Local Safe" },
    { n: "5,000", ram: "100 MB", status: "Local Safe (Capped)" },
    { n: "10,000", ram: "400 MB", status: "Boundary / Slow" },
    { n: "100,000", ram: "40 GB", status: "OOM Crash / Out of Memory", isCrash: true },
    { n: "1,000,000+", ram: "4 TB", status: "Physically Impossible Locally", isFatal: true },
  ];

  return (
    <div className="border border-destructive/20 bg-card p-6 md:p-8 rounded-sm shadow-none">
      <div className="flex items-center gap-2 mb-6">
        <span className="h-2 w-2 rounded-full bg-destructive animate-pulse"></span>
        <h3 className="font-display text-xl md:text-2xl text-foreground">
          The O(N^2) Memory Wall: Why Local Clustering Fails
        </h3>
      </div>

      <p className="text-sm text-muted-foreground leading-relaxed mb-6">
        Traditional clustering models (such as local pairwise connected components) require computing a contiguous, 
        dense similarity matrix in memory. Because space requirements grow quadratically, 
        analyzing standard agency dockets quickly causes the system to crash.
      </p>

      {/* Scaling Table */}
      <div className="border border-rule rounded-sm overflow-hidden mb-6">
        <table className="w-full text-left border-collapse text-xs">
          <thead>
            <tr className="bg-secondary border-b border-rule">
              <th className="p-3 font-sans uppercase tracking-wider text-muted-foreground">Sample Size (N)</th>
              <th className="p-3 font-sans uppercase tracking-wider text-muted-foreground">Required Float32 RAM</th>
              <th className="p-3 font-sans uppercase tracking-wider text-muted-foreground">Single-Node Status</th>
            </tr>
          </thead>
          <tbody>
            {scalingData.map((row, idx) => (
              <tr
                key={idx}
                className={`border-b border-rule last:border-0 ${
                  row.isCrash
                    ? "bg-destructive/5 text-destructive font-medium"
                    : row.isFatal
                    ? "bg-destructive/10 text-destructive font-bold"
                    : "text-foreground"
                }`}
              >
                <td className="p-3 font-mono tabular-nums">{row.n} comments</td>
                <td className="p-3 font-mono tabular-nums">{row.ram}</td>
                <td className="p-3 flex items-center gap-2 font-mono">
                  {(row.isCrash || row.isFatal) && <span className="font-semibold">!</span>}\r\n                  {row.status}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Physics Warning */}
      <div className="p-4 border-l-2 border-destructive bg-destructive/5 text-xs text-muted-foreground leading-relaxed">
        <strong className="text-destructive font-sans uppercase tracking-wider block mb-1">
          Physical Physics Threshold Exceeded
        </strong>
        Under a docket with 100K comments, we perform **4,999,950,000 pairwise comparisons** (10 Billion float operations). 
        To prevent Out-of-Memory crashes, our production clustering agent replaces expensive contiguous matrices with 
        **Databricks Vector Search**, reducing query complexity to sub-quadratic O(N log N) using distributed HNSW indexing.
      </div>
    </div>
  );
}
