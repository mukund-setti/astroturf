export function IntroSection() {
  return (
    <section className="border-b border-rule">
      <div className="mx-auto max-w-[640px] px-6 py-20 md:py-28">
        <div className="space-y-7 text-foreground">
          <p className="text-xl md:text-2xl leading-snug">
            In 2017, the Federal Communications Commission received 22 million
            public comments on its proposal to repeal net neutrality. Four
            years later, the New York Attorney General concluded that roughly
            18 million of those comments were fake. Three lead generators
            settled for $4.4 million. The broadband industry&rsquo;s lobbying
            group had spent $4.2 million to generate 8.5 million fraudulent
            comments using the names and personal information of real people
            without their consent. The astroturf went undetected during the
            comment period.
          </p>
          <p className="text-lg md:text-xl leading-relaxed">
            Astroturf detects coordinated public comment campaigns in federal
            rulemaking. Built on Databricks, it ingests comments from
            regulations.gov and FCC ECFS, generates semantic embeddings via
            the Databricks Foundation Model API, clusters textually similar
            messages using Databricks Vector Search, and surfaces patterns
            that distinguish real grassroots engagement from manufactured
            consensus.
          </p>
          <p className="text-sm uppercase tracking-[0.22em] text-muted-foreground pt-2 leading-relaxed">
            Below is one finding from one EPA rulemaking.
            <br />
            The FCC docket is the next target.
          </p>
        </div>
      </div>
    </section>
  );
}
