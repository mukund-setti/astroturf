// Consumer-facing topic taxonomy for the new /, /explore, and /topic/[slug]
// surfaces. This intentionally diverges from ui/lib/fallback-data.ts, which
// preserves the legacy technical-first taxonomy (telecom, oil_and_gas,
// finance) for the rehomed /legacy/* routes.
//
// "the-economy" is a gathering topic: it surfaces findings from itself
// PLUS its child slugs (banking-and-lending, labor). Users think in broad
// strokes; the system clusters narrowly.

export interface Topic {
  slug: string;
  label: string;
  keywords: string[];
  /** If set, listFindingsByTopic also includes findings tagged with these slugs. */
  gathers?: string[];
}

export const TOPICS: Topic[] = [
  {
    slug: "the-economy",
    label: "the economy",
    keywords: [
      "economy",
      "banking",
      "lending",
      "consumer-protection",
      "fiduciary",
      "overdraft",
      "payday",
      "jobs",
      "wages",
      "workers",
    ],
    gathers: ["banking-and-lending", "labor"],
  },
  {
    slug: "climate",
    label: "climate change",
    keywords: [
      "climate",
      "methane",
      "carbon",
      "emissions",
      "clean-power",
      "waters",
      "epa",
      "global-warming",
    ],
  },
  {
    slug: "health-care",
    label: "health care",
    keywords: [
      "health",
      "medicare",
      "medicaid",
      "hospital",
      "drug",
      "cms",
      "price-transparency",
      "insurance",
    ],
  },
  {
    slug: "tech-regulation",
    label: "tech regulation",
    keywords: [
      "internet",
      "broadband",
      "net-neutrality",
      "fcc",
      "telecom",
      "isp",
      "ai",
      "algorithm",
    ],
  },
  {
    slug: "banking-and-lending",
    label: "banking and lending",
    keywords: [
      "banking",
      "lending",
      "consumer-finance",
      "credit",
      "cfpb",
      "fiduciary",
      "overdraft",
      "payday",
    ],
  },
  {
    slug: "environment",
    label: "environment",
    keywords: [
      "environment",
      "pollution",
      "emissions",
      "water",
      "air",
      "epa",
      "wetlands",
    ],
  },
  {
    slug: "labor",
    label: "workers and jobs",
    keywords: [
      "labor",
      "employment",
      "workplace",
      "wages",
      "dol",
      "osha",
      "overtime",
    ],
  },
];

export function getTopicBySlug(slug: string): Topic | undefined {
  return TOPICS.find((t) => t.slug === slug);
}

/**
 * Slugs a query against - its own slug plus any `gathers` children. Use
 * this when building `WHERE topic_slug IN (...)` queries on `findings`.
 */
export function topicSlugsForQuery(slug: string): string[] {
  const topic = getTopicBySlug(slug);
  if (!topic) return [slug];
  return [topic.slug, ...(topic.gathers ?? [])];
}

/**
 * Maps a docket to a topic slug. Manual mapping for the curated dockets
 * wins; otherwise falls back to agency-based defaults and finally to
 * "the-economy" so nothing lands in nowhere.
 */
export function topicForDocket(
  docket_id: string,
  agency_id?: string,
  _tags?: string[],
): string {
  const manual: Record<string, string> = {
    "FCC-17-108": "tech-regulation",
    "17-108": "tech-regulation",
    "CFPB-2016-0025": "banking-and-lending",
    "EPA-HQ-OAR-2021-0317": "climate",
    "CMS-2019-0193": "health-care",
    "EPA-HQ-OAR-2013-0602": "climate",
    "DOL-2010-0050": "banking-and-lending",
    "FCC-14-28": "tech-regulation",
    "CMS-2018-0114": "health-care",
    "EPA-HQ-OW-2021-0602": "environment",
    "CFPB-2018-0035": "banking-and-lending",
    "FTC-2023-0007": "tech-regulation",
    "CMS-2019-0006": "health-care",
  };
  if (manual[docket_id]) return manual[docket_id];

  const upper = (agency_id ?? "").toUpperCase();
  if (upper === "FCC") return "tech-regulation";
  if (upper === "FTC") return "tech-regulation";
  if (upper === "NHTSA") return "tech-regulation";
  if (upper === "EPA") return "climate";
  if (upper === "CMS") return "health-care";
  if (upper === "HHS" || upper === "HHS-OCR") return "health-care";
  if (upper === "FDA") return "health-care";
  if (upper === "DEA") return "health-care";
  if (upper === "CFPB") return "banking-and-lending";
  if (upper === "DOL") return "labor";
  if (upper === "OSHA") return "labor";
  if (upper === "BIS") return "the-economy";

  return "the-economy";
}
