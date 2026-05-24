export interface DocketCopy {
  docket_id: string;
  agency_short: string;
  rule_title: string;
  rule_short_name: string;
  context_sentence: string;
}

/**
 * Human-readable copy per docket. The UI looks up `docket_id` at render time
 * and falls back to a docket-agnostic string if no entry exists, so adding a
 * new docket to the demo is a copy-only change.
 */
export const DOCKET_COPY: Record<string, DocketCopy> = {
  "EPA-HQ-OAR-2021-0317": {
    docket_id: "EPA-HQ-OAR-2021-0317",
    agency_short: "EPA",
    rule_title:
      "EPA Standards of Performance for New, Reconstructed, and Modified Sources, and Emissions Guidelines for Existing Sources: Oil and Natural Gas Sector Climate Review",
    rule_short_name: "methane rule",
    context_sentence:
      "Public comments on EPA's methane emissions standards for the oil and gas sector.",
  },
  "CFPB-2016-0025": {
    docket_id: "CFPB-2016-0025",
    agency_short: "CFPB",
    rule_title:
      "CFPB Payday, Vehicle Title, and Certain High-Cost Installment Loans",
    rule_short_name: "payday lending rule",
    context_sentence:
      "Public comments on the CFPB's payday lending rule.",
  },
  "17-108": {
    docket_id: "17-108",
    agency_short: "FCC",
    rule_title:
      "FCC Restoring Internet Freedom Proceeding (Net Neutrality Deregulation)",
    rule_short_name: "Net Neutrality repeal",
    context_sentence:
      "Public comments under proceeding 17-108 in the historic Restoring Internet Freedom debate.",
  },
};

export function getDocketCopy(docket_id: string): DocketCopy {
  return (
    DOCKET_COPY[docket_id] ?? {
      docket_id,
      agency_short: docket_id.split("-")[0] ?? "the agency",
      rule_title: docket_id,
      rule_short_name: "rulemaking",
      context_sentence: `Public comments on docket ${docket_id}.`,
    }
  );
}
