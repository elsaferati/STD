const STATUS_KEYS = [
  "ok",
  "waitingForReply",
  "updatedAfterReply",
  "humanInTheLoop",
  "post",
  "unknownClient",
  "failed",
];

function toNumber(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

export function getStatusBreakdownTotal(day) {
  return STATUS_KEYS.reduce((sum, key) => sum + toNumber(day?.[key]), 0);
}

export function calculateStatusPercentages(day) {
  const total = getStatusBreakdownTotal(day);
  return STATUS_KEYS.reduce(
    (percentages, key) => {
      percentages[key] = total > 0 ? (toNumber(day?.[key]) / total) * 100 : 0;
      return percentages;
    },
    { total },
  );
}

export { STATUS_KEYS };
