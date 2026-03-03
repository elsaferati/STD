export const ALL_CLIENT_FILTER = "all";
export const UNKNOWN_CLIENT_BRANCH_ID = "unknown";

export const CLIENT_BRANCHES = [
  {
    id: "xxxlutz_default",
    labelKey: "clients.branch.xxxlutz_default",
    defaultLabel: "XXXLutz Default",
  },
  {
    id: "momax_bg",
    labelKey: "clients.branch.momax_bg",
    defaultLabel: "MOMAX BG",
  },
  {
    id: "porta",
    labelKey: "clients.branch.porta",
    defaultLabel: "Porta",
  },
  {
    id: "braun",
    labelKey: "clients.branch.braun",
    defaultLabel: "Braun",
  },
  {
    id: "segmuller",
    labelKey: "clients.branch.segmuller",
    defaultLabel: "Segmuller",
  },
];

export const KNOWN_CLIENT_BRANCH_IDS = new Set(CLIENT_BRANCHES.map((branch) => branch.id));
