export type CoverageStatus =
  | "analyzed"
  | "baseline_only"
  | "ingestion_ready"
  | "hidden";

export interface Topic {
  id: string;
  name: string;
  agencies: string[];
  docketsCount: number;
  campaignsCount: number;
  status: CoverageStatus;
  visibility: "primary" | "template" | "hidden";
  description: string;
  dockets: string[];
  actionLabel?: string;
  statusLabel: string;
}

export interface Agency {
  id: string;
  name: string;
  fullName: string;
  policyDomains: string[];
  docketsCount: number;
  totalComments: number;
  campaignsCount: number;
  status: CoverageStatus;
  visibility: "primary" | "supported_source" | "hidden";
  statusLabel: string;
}

export interface Docket {
  id: string;
  title: string;
  agencyId: string;
  topicId: string;
  totalComments: number;
  commentsInClusters: number;
  clusterCount: number;
  largestClusterSize: number;
  status: Exclude<CoverageStatus, "hidden">;
  ruleShortName: string;
  ruleTitle: string;
  description: string;
  statusLabel: string;
  validationSummary: string;
  nextStep?: string;
  isExactHashOnly?: boolean;
}

export const TOPICS: Topic[] = [
  {
    id: "telecom",
    name: "Telecom & Net Neutrality",
    agencies: ["FCC"],
    docketsCount: 1,
    campaignsCount: 3,
    status: "analyzed",
    visibility: "primary",
    statusLabel: "Live Databricks validated",
    description:
      "Semantic clustering and Vector Search validation for the FCC 17-108 Net Neutrality proceeding.",
    dockets: ["17-108"],
  },
  {
    id: "oil_and_gas",
    name: "Climate / Oil & Gas / Methane",
    agencies: ["EPA"],
    docketsCount: 1,
    campaignsCount: 7,
    status: "baseline_only",
    visibility: "primary",
    statusLabel: "Baseline only; semantic clustering queued",
    description:
      "Exact-hash duplicate baseline for EPA methane comments, with semantic clustering still pending.",
    dockets: ["EPA-HQ-OAR-2021-0317"],
  },
  {
    id: "analyze",
    name: "Analyze a Rulemaking",
    agencies: ["FCC", "EPA", "CFPB", "FTC", "SEC"],
    docketsCount: 0,
    campaignsCount: 0,
    status: "ingestion_ready",
    visibility: "primary",
    statusLabel: "Ready for ingestion",
    actionLabel: "Generate pipeline config",
    description:
      "Register a regulations.gov or FCC ECFS docket and generate the pipeline command sequence.",
    dockets: [],
  },
  {
    id: "finance",
    name: "Finance & Consumer Protection",
    agencies: ["CFPB", "SEC"],
    docketsCount: 1,
    campaignsCount: 0,
    status: "ingestion_ready",
    visibility: "template",
    statusLabel: "Configured, awaiting run",
    description:
      "Registered ingestion templates for CFPB payday lending and SEC digital asset rulemakings.",
    dockets: ["CFPB-2016-0025"],
  },
  {
    id: "ai_regulation",
    name: "AI & Technology Regulation",
    agencies: ["FTC"],
    docketsCount: 0,
    campaignsCount: 0,
    status: "ingestion_ready",
    visibility: "template",
    statusLabel: "Ready for ingestion",
    description:
      "Template coverage for algorithmic transparency or consumer safety rulemakings once a docket is registered.",
    dockets: [],
  },
  {
    id: "privacy",
    name: "Privacy & Consumer Protection",
    agencies: ["FTC", "FCC"],
    docketsCount: 0,
    campaignsCount: 0,
    status: "ingestion_ready",
    visibility: "template",
    statusLabel: "Ready for ingestion",
    description:
      "Template coverage for privacy, robocall, and data-protection dockets.",
    dockets: [],
  },
  {
    id: "healthcare",
    name: "Healthcare",
    agencies: ["FDA"],
    docketsCount: 0,
    campaignsCount: 0,
    status: "hidden",
    visibility: "hidden",
    statusLabel: "Not yet registered",
    description:
      "Future coverage area; register a specific FDA docket before it appears in primary browsing.",
    dockets: [],
  },
  {
    id: "labor",
    name: "Labor & Workplace",
    agencies: ["FTC"],
    docketsCount: 0,
    campaignsCount: 0,
    status: "hidden",
    visibility: "hidden",
    statusLabel: "Not yet registered",
    description:
      "Future coverage area; register a specific workplace rulemaking before it appears in primary browsing.",
    dockets: [],
  },
];

export const AGENCIES: Agency[] = [
  {
    id: "FCC",
    name: "FCC",
    fullName: "Federal Communications Commission",
    policyDomains: ["Telecom & Net Neutrality"],
    docketsCount: 1,
    totalComments: 4993,
    campaignsCount: 3,
    status: "analyzed",
    visibility: "primary",
    statusLabel: "Live Databricks validated",
  },
  {
    id: "EPA",
    name: "EPA",
    fullName: "Environmental Protection Agency",
    policyDomains: ["Climate / Oil & Gas / Methane"],
    docketsCount: 1,
    totalComments: 396,
    campaignsCount: 7,
    status: "baseline_only",
    visibility: "primary",
    statusLabel: "Baseline only",
  },
  {
    id: "CFPB",
    name: "CFPB",
    fullName: "Consumer Financial Protection Bureau",
    policyDomains: ["Finance & Consumer Protection"],
    docketsCount: 1,
    totalComments: 211885,
    campaignsCount: 0,
    status: "ingestion_ready",
    visibility: "supported_source",
    statusLabel: "Configured, awaiting run",
  },
  {
    id: "FTC",
    name: "FTC",
    fullName: "Federal Trade Commission",
    policyDomains: ["AI & Technology Regulation", "Privacy & Consumer Protection"],
    docketsCount: 0,
    totalComments: 0,
    campaignsCount: 0,
    status: "ingestion_ready",
    visibility: "supported_source",
    statusLabel: "Ready for ingestion",
  },
  {
    id: "SEC",
    name: "SEC",
    fullName: "Securities and Exchange Commission",
    policyDomains: ["Finance & Consumer Protection"],
    docketsCount: 0,
    totalComments: 0,
    campaignsCount: 0,
    status: "ingestion_ready",
    visibility: "supported_source",
    statusLabel: "Ready for ingestion",
  },
  {
    id: "FDA",
    name: "FDA",
    fullName: "Food and Drug Administration",
    policyDomains: ["Healthcare"],
    docketsCount: 0,
    totalComments: 0,
    campaignsCount: 0,
    status: "hidden",
    visibility: "hidden",
    statusLabel: "Not yet registered",
  },
  {
    id: "DOE",
    name: "DOE",
    fullName: "Department of Energy",
    policyDomains: ["Energy"],
    docketsCount: 0,
    totalComments: 0,
    campaignsCount: 0,
    status: "hidden",
    visibility: "hidden",
    statusLabel: "Not yet registered",
  },
];

export const DOCKETS: Docket[] = [
  {
    id: "17-108",
    title: "Restoring Internet Freedom",
    agencyId: "FCC",
    topicId: "telecom",
    totalComments: 4993,
    commentsInClusters: 1017,
    clusterCount: 3,
    largestClusterSize: 1002,
    status: "analyzed",
    statusLabel: "Live Databricks validated",
    validationSummary:
      "500-comment controlled slice validated on Databricks Serverless with Vector Search clustering and export.",
    ruleShortName: "net neutrality repeal",
    ruleTitle:
      "FCC Restoring Internet Freedom Proceeding (Net Neutrality Deregulation)",
    description:
      "Historic debate on classification of broadband internet providers as common carriers under Title II of the Communications Act.",
  },
  {
    id: "EPA-HQ-OAR-2021-0317",
    title: "Methane Sector Climate Review",
    agencyId: "EPA",
    topicId: "oil_and_gas",
    totalComments: 396,
    commentsInClusters: 16,
    clusterCount: 7,
    largestClusterSize: 4,
    status: "baseline_only",
    statusLabel: "Baseline only; semantic clustering queued",
    validationSummary:
      "Exact normalized-text hash baseline found 7 duplicate clusters across 16 comments from 396 parsed rows.",
    ruleShortName: "methane rule",
    ruleTitle:
      "EPA Standards of Performance for New, Reconstructed, and Modified Sources: Oil and Natural Gas Sector Climate Review",
    description:
      "Proposed standards of performance and emissions guidelines for methane limits in the oil and gas sector. Processed through exact-hash baseline only; semantic embedding clustering has not been promoted for this docket.",
    nextStep:
      "Run the Databricks workflow embed and cluster tasks with clustering_mode=\"vector_search\" for EPA-HQ-OAR-2021-0317.",
    isExactHashOnly: true,
  },
  {
    id: "CFPB-2016-0025",
    title: "Payday & Short-Term Loans",
    agencyId: "CFPB",
    topicId: "finance",
    totalComments: 211885,
    commentsInClusters: 0,
    clusterCount: 0,
    largestClusterSize: 0,
    status: "ingestion_ready",
    statusLabel: "Configured, awaiting run",
    validationSummary:
      "Bronze ingestion and deterministic parsing exist locally; campaign clustering is not surfaced in the product yet.",
    ruleShortName: "payday lending rule",
    ruleTitle: "CFPB Payday, Vehicle Title, and Certain High-Cost Installment Loans",
    description:
      "Regulatory review of credit terms and consumer underwriting criteria for payday lending and auto-title loan programs.",
    nextStep:
      "Use Analyze a docket to generate a Databricks workflow command before promoting this into primary browsing.",
  },
  {
    id: "SEC-2023-0001",
    title: "Digital Asset Custody Requirements",
    agencyId: "SEC",
    topicId: "finance",
    totalComments: 15000,
    commentsInClusters: 0,
    clusterCount: 0,
    largestClusterSize: 0,
    status: "ingestion_ready",
    statusLabel: "Configured, awaiting run",
    validationSummary:
      "Registered ingestion template only; no processed campaign results.",
    ruleShortName: "digital asset custody",
    ruleTitle:
      "SEC Digital Asset Custody Requirements for Registered Investment Advisers",
    description:
      "SEC rulemaking on custody requirements for registered investment advisers handling digital assets.",
    nextStep:
      "Use Analyze a docket to generate a Databricks workflow command before promoting this into primary browsing.",
  },
];

export const PRIMARY_TOPICS = TOPICS.filter((t) => t.visibility === "primary");
export const PRIMARY_ANALYSIS_TOPICS = TOPICS.filter(
  (t) => t.visibility === "primary" && t.id !== "analyze",
);
export const INGESTION_TEMPLATE_TOPICS = TOPICS.filter(
  (t) => t.visibility === "template",
);
export const PRIMARY_AGENCIES = AGENCIES.filter(
  (a) => a.visibility === "primary",
);
export const SUPPORTED_SOURCE_AGENCIES = AGENCIES.filter(
  (a) => a.visibility === "supported_source",
);

export function getTopicById(id: string): Topic | undefined {
  return TOPICS.find((t) => t.id === id);
}

export function getAgencyById(id: string): Agency | undefined {
  return AGENCIES.find((a) => a.id.toLowerCase() === id.toLowerCase());
}

export function getDocketById(id: string): Docket | undefined {
  return DOCKETS.find((d) => d.id.toLowerCase() === id.toLowerCase());
}

export function getDocketsForTopic(topicId: string): Docket[] {
  return DOCKETS.filter((d) => d.topicId === topicId);
}

export function getDocketsForAgency(agencyId: string): Docket[] {
  return DOCKETS.filter((d) => d.agencyId.toLowerCase() === agencyId.toLowerCase());
}
