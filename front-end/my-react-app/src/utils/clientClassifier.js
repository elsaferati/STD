import { KNOWN_CLIENT_BRANCH_IDS, UNKNOWN_CLIENT_BRANCH_ID } from "../constants/clientBranches";

const ROUTING_SELECTED_RE = /Routing:\s*selected=([a-z0-9_]+)/i;

export function normalizeBranchId(value) {
  const branchId = String(value || "").trim().toLowerCase();
  if (KNOWN_CLIENT_BRANCH_IDS.has(branchId)) {
    return branchId;
  }
  return UNKNOWN_CLIENT_BRANCH_ID;
}

export function extractBranchFromWarnings(warnings) {
  if (!Array.isArray(warnings)) {
    return UNKNOWN_CLIENT_BRANCH_ID;
  }

  for (const warning of warnings) {
    const text = String(warning || "");
    const match = text.match(ROUTING_SELECTED_RE);
    if (match?.[1]) {
      return normalizeBranchId(match[1]);
    }
  }

  return UNKNOWN_CLIENT_BRANCH_ID;
}
