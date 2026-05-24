export function HowItHides() {
  const comments = [
    {
      author: "Eleanor Vance",
      id: "108282535307158",
      similarity: "99.0%",
      hash: "e93f...78a1",
      preface: "I grew up with our internet and throughout my time I have had great times with our internet on a variety of sites and this new plan could take away things...",
      body: "We need the FCC to defend the rights of millions of Internet users by upholding net neutrality protections. I stand with the millions of other Internet users who’ve urged the Commission to keep important net neutrality protections intact. The FCC should reject Chairman Ajit Pai’s plan to hand the government-subsidized ISP monopolies...",
      mutation: "Substituted 'proposal' with 'plan', and 'telecom giants' with 'ISP monopolies' inside the core template text.",
    },
    {
      author: "Gregory House",
      id: "1082893935836",
      similarity: "98.4%",
      hash: "82a9...d32b",
      preface: "As a doctor and professional in the healthcare space, open internet access means that online research and medical databases load immediately for all individuals...",
      body: "We need the FCC to defend the rights of millions of Internet users by upholding net neutrality protections. I stand with the millions of other Internet users who’ve urged the Commission to keep important net neutrality protections intact. The FCC should reject Chairman Ajit Pai’s proposal to give government-subsidized telecom...",
      mutation: "Injected a completely unique professional preface in the first paragraph, and replaced 'Comcast, AT&T, and Verizon' with 'telecom giants'.",
    },
    {
      author: "Robert Chase",
      id: "108280080014462",
      similarity: "98.3%",
      hash: "f45c...0012",
      preface: "The internet belongs to everyone and should remain free of gatekeepers who veto expression.",
      body: "We need the FCC to defend the rights of millions of Internet users by upholding net neutrality protections. I stand with the millions of other Internet users who’ve urged the Commission to keep important net neutrality protections intact. The FCC should reject Chairman Ajit Pai’s proposal to hand the government-subsidized...",
      mutation: "Added a brief philosophical postscript at the tail end of the submission, leaving the inner body text unmodified.",
    },
  ];

  return (
    <div className="border border-rule bg-card p-6 md:p-8 rounded-sm shadow-none">
      <div className="flex items-center gap-2 mb-6">
        <span className="h-2 w-2 rounded-full bg-brand"></span>
        <h3 className="font-display text-xl md:text-2xl text-foreground">
          How the Coordinated Campaign Hides Itself
        </h3>
      </div>

      <p className="text-sm text-muted-foreground leading-relaxed mb-6">
        Observe these three actual submissions from FCC docket **17-108**. By injecting personalized 
        prefaces, swapping select words, or adding custom postscripts, each filer generated a **completely 
        diverging text hash**, making them look unique to keyword filters. Yet, their core template and 
        **98%+ semantic similarity** remain identical.
      </p>

      {/* Columns Grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {comments.map((comment, idx) => (
          <div key={idx} className="border border-rule bg-secondary/10 p-5 rounded-sm flex flex-col justify-between">
            <div>
              {/* Header Info */}
              <div className="flex items-center justify-between border-b border-rule pb-3 mb-4">
                <div>
                  <h4 className="font-sans font-semibold text-foreground text-sm">
                    {comment.author}
                  </h4>
                  <span className="text-[10px] text-muted-foreground font-mono">
                    ID: {comment.id}
                  </span>
                </div>
                <div className="text-right">
                  <span className="font-mono text-xs font-semibold text-brand block">
                    {comment.similarity} Sim
                  </span>
                  <span className="text-[9px] text-muted-foreground font-mono block">
                    Hash: {comment.hash}
                  </span>
                </div>
              </div>

              {/* Text Preview */}
              <div className="text-xs leading-relaxed max-h-[220px] overflow-y-auto mb-4 border-b border-rule pb-4 pr-1 font-sans">
                {/* Preface Highlight */}
                {comment.preface && (
                  <span className="bg-brand/10 text-brand px-1.5 py-0.5 rounded-sm italic block mb-2">
                    [Custom Input] &ldquo;{comment.preface}&rdquo;
                  </span>
                )}
                <span className="text-foreground/80">
                  {comment.body.slice(0, 200)}...
                </span>
              </div>
            </div>

            {/* Mutation Analysis */}
            <div className="mt-auto">
              <span className="text-[9px] font-sans uppercase tracking-wider text-muted-foreground font-semibold block">
                Mutation analysis
              </span>
              <p className="text-[11px] text-muted-foreground leading-snug italic mt-1">
                {comment.mutation}
              </p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
