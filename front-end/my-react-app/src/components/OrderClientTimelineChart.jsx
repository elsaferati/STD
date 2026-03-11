import { useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const CLIENT_COLORS = ["#2563eb", "#16a34a", "#f97316", "#7c3aed", "#ec4899", "#0f766e", "#eab308"];
const CLIENT_GROUPS = [
  {
    id: "braun",
    label: "Braun",
    sourceIds: ["braun"],
  },
  {
    id: "momax_bg",
    label: "MOMAX / AIKO",
    sourceIds: ["momax_bg"],
  },
  {
    id: "porta",
    label: "Porta",
    sourceIds: ["porta"],
  },
  {
    id: "segmuller",
    label: "Segmuller",
    sourceIds: ["segmuller"],
  },
  {
    id: "unknown",
    label: "Unknown",
    sourceIds: ["unknown"],
  },
  {
    id: "xxxlutz",
    label: "XXXLutz",
    sourceIds: ["xxxlutz_default", "xxxlutz_zusatzliche"],
  },
];
const SIX_HOUR_BLOCKS = [
  { key: "night", start: 0, end: 6, label: "Night" },
  { key: "morning", start: 6, end: 12, label: "Morning" },
  { key: "afternoon", start: 12, end: 18, label: "Afternoon" },
  { key: "evening", start: 18, end: 24, label: "Evening" },
];

function toShortDayLabel(value, locale) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value || "");
  }
  return date.toLocaleDateString(locale || undefined, { weekday: "short", day: "2-digit" });
}

function toShortDateLabel(value, locale) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value || "");
  }
  return date.toLocaleDateString(locale || undefined, { month: "short", day: "2-digit" });
}

function buildColorMap(clients) {
  return clients.reduce((accumulator, client, index) => {
    accumulator[client.id] = CLIENT_COLORS[index % CLIENT_COLORS.length];
    return accumulator;
  }, {});
}

function normalizeTimeline(timeline) {
  const rawClients = timeline?.clients || [];
  const rawDays = timeline?.days || [];
  const availableIds = new Set(rawClients.map((client) => String(client?.id || "").trim()).filter(Boolean));

  const clients = CLIENT_GROUPS.filter((group) => group.sourceIds.some((sourceId) => availableIds.has(sourceId)));
  const clientSourceMap = new Map(clients.map((client) => [client.id, client.sourceIds]));

  const days = rawDays.map((day) => {
    const hours = Array.from({ length: 24 }, (_, hour) => {
      const hourEntry = (day.hours || []).find((entry) => Number(entry?.hour) === hour) || { hour, total: 0, clients: [] };
      const countById = new Map(
        (hourEntry.clients || []).map((entry) => [String(entry?.id || "").trim(), Number(entry?.count || 0)]),
      );
      const groupedClients = clients
        .map((client) => {
          const count = (clientSourceMap.get(client.id) || []).reduce(
            (sum, sourceId) => sum + Number(countById.get(sourceId) || 0),
            0,
          );
          return { id: client.id, count };
        })
        .filter((client) => client.count > 0);

      return {
        hour,
        label: `${String(hour).padStart(2, "0")}:00`,
        total: groupedClients.reduce((sum, client) => sum + client.count, 0),
        clients: groupedClients,
      };
    });

    return {
      date: day.date,
      label: day.label,
      total: hours.reduce((sum, entry) => sum + entry.total, 0),
      hours,
    };
  });

  return { clients, days };
}

function buildClientSeries(days, clients) {
  return days.map((day) => {
    const hourMap = new Map((day.hours || []).map((entry) => [entry.hour, entry]));
    return {
      date: day.date,
      label: day.label,
      hours: Array.from({ length: 24 }, (_, hour) => {
        const hourEntry = hourMap.get(hour) || { hour, total: 0, clients: [] };
        const point = {
          hour,
          label: `${String(hour).padStart(2, "0")}:00`,
          total: Number(hourEntry.total || 0),
        };
        clients.forEach((client) => {
          const clientEntry = (hourEntry.clients || []).find((entry) => entry.id === client.id);
          point[client.id] = Number(clientEntry?.count || 0);
        });
        return point;
      }),
    };
  });
}

function buildWeeklySeries(daySeries, clients, locale) {
  return clients.map((client) => ({
    id: client.id,
    label: client.label,
    data: daySeries.flatMap((day) =>
      day.hours.map((hourPoint) => ({
        key: `${day.date}-${hourPoint.hour}`,
        xLabel: `${toShortDayLabel(day.date, locale)} ${hourPoint.label}`,
        shortLabel: hourPoint.label,
        count: Number(hourPoint[client.id] || 0),
      })),
    ),
  }));
}

function buildMonthlySeries(daySeries, clients, locale) {
  return daySeries.flatMap((day) =>
    SIX_HOUR_BLOCKS.map((block) => {
      const point = {
        key: `${day.date}-${block.key}`,
        xLabel: `${toShortDateLabel(day.date, locale)} ${block.label}`,
        block: block.label,
      };
      clients.forEach((client) => {
        point[client.id] = day.hours
          .filter((hourEntry) => hourEntry.hour >= block.start && hourEntry.hour < block.end)
          .reduce((sum, hourEntry) => sum + Number(hourEntry[client.id] || 0), 0);
      });
      return point;
    }),
  );
}

function ClientTooltip({ active, payload, label, clientMap }) {
  if (!active || !payload?.length) {
    return null;
  }

  return (
    <div className="rounded-xl border border-slate-200 bg-white px-3 py-2 shadow-lg">
      <div className="text-xs font-semibold text-slate-900">{label}</div>
      <div className="mt-2 space-y-1">
        {payload
          .filter((entry) => Number(entry.value || 0) > 0)
          .map((entry) => (
            <div key={entry.dataKey} className="flex items-center justify-between gap-3 text-xs">
              <span className="flex items-center gap-2 text-slate-600">
                <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: entry.color }} />
                <span>{clientMap.get(entry.dataKey) || entry.dataKey}</span>
              </span>
              <span className="font-semibold text-slate-900">{entry.value}</span>
            </div>
          ))}
      </div>
    </div>
  );
}

export function generateOrderClientTimelineMockData({ days = 30, seed = 17 } = {}) {
  const clients = [
    { id: "xxxlutz_default", label: "XXXLutz" },
    { id: "porta", label: "Porta" },
    { id: "momax_bg", label: "MOMAX BG" },
    { id: "braun", label: "Braun" },
    { id: "segmuller", label: "Segmuller" },
    { id: "unknown", label: "Unknown" },
    { id: "custom_client", label: "Client 7" },
  ];

  let currentSeed = seed;
  const random = () => {
    currentSeed = (currentSeed * 9301 + 49297) % 233280;
    return currentSeed / 233280;
  };

  const start = new Date();
  start.setHours(0, 0, 0, 0);
  start.setDate(start.getDate() - (days - 1));

  const timelineDays = Array.from({ length: days }, (_, dayIndex) => {
    const date = new Date(start);
    date.setDate(start.getDate() + dayIndex);

    const hours = Array.from({ length: 24 }, (_, hour) => {
      const clientsForHour = clients.map((client, clientIndex) => {
        const daytimeBoost = hour >= 7 && hour <= 18 ? 1.35 : 0.45;
        const weeklyBoost = date.getDay() === 1 || date.getDay() === 2 ? 1.15 : 0.95;
        const clientBias = 1 + (clientIndex * 0.08);
        const wave = Math.sin(((hour + clientIndex) / 24) * Math.PI * 2) + 1.25;
        const count = Math.max(0, Math.round(random() * 4 * daytimeBoost * weeklyBoost * clientBias * wave));
        return { id: client.id, count };
      });

      return {
        hour,
        label: `${String(hour).padStart(2, "0")}:00`,
        total: clientsForHour.reduce((sum, entry) => sum + entry.count, 0),
        clients: clientsForHour.filter((entry) => entry.count > 0),
      };
    });

    return {
      date: date.toISOString(),
      label: date.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" }),
      total: hours.reduce((sum, entry) => sum + entry.total, 0),
      hours,
    };
  });

  return { clients, days: timelineDays };
}

export function OrderClientTimelineChart({
  timeline,
  view = "daily",
  locale,
}) {
  const normalizedTimeline = useMemo(() => normalizeTimeline(timeline), [timeline]);
  const clients = normalizedTimeline.clients;
  const days = normalizedTimeline.days;
  const colorMap = useMemo(() => buildColorMap(clients), [clients]);
  const clientMap = useMemo(() => new Map(clients.map((client) => [client.id, client.label])), [clients]);
  const [hiddenClientIds, setHiddenClientIds] = useState([]);
  const [selectedDailyDate, setSelectedDailyDate] = useState(() => (days.length ? days[days.length - 1].date : null));

  const visibleClients = clients.filter((client) => !hiddenClientIds.includes(client.id));
  const daySeries = useMemo(() => buildClientSeries(days, clients), [days, clients]);

  const selectedDailySeries =
    daySeries.find((day) => day.date === selectedDailyDate)
    || daySeries[daySeries.length - 1]
    || null;

  const weeklySeries = useMemo(() => buildWeeklySeries(daySeries.slice(-7), clients, locale), [clients, daySeries, locale]);
  const monthlySeries = useMemo(() => buildMonthlySeries(daySeries, clients, locale), [clients, daySeries, locale]);

  const toggleClient = (clientId) => {
    setHiddenClientIds((current) => (
      current.includes(clientId)
        ? current.filter((value) => value !== clientId)
        : [...current, clientId]
    ));
  };

  if (!clients.length || !days.length) {
    return (
      <div className="min-h-[180px] flex items-center justify-center rounded-2xl border border-dashed border-slate-200 text-sm text-slate-400">
        No timeline data available.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {clients.map((client) => {
          const hidden = hiddenClientIds.includes(client.id);
          return (
            <button
              key={client.id}
              type="button"
              onClick={() => toggleClient(client.id)}
              className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors ${
                hidden ? "border-slate-200 bg-white text-slate-400" : "border-slate-300 bg-slate-50 text-slate-700"
              }`}
            >
              <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: colorMap[client.id] }} />
              <span>{client.label}</span>
            </button>
          );
        })}
      </div>

      {view === "daily" ? (
        <div className="space-y-4">
          {days.length > 1 ? (
            <div className="flex flex-wrap gap-2">
              {days.map((day) => (
                <button
                  key={day.date}
                  type="button"
                  onClick={() => setSelectedDailyDate(day.date)}
                  className={`rounded-xl border px-3 py-2 text-left text-xs transition-colors ${
                    selectedDailySeries?.date === day.date
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                  }`}
                >
                  <div className="font-semibold">{day.label}</div>
                  <div className="mt-1 opacity-80">{day.total} orders</div>
                </button>
              ))}
            </div>
          ) : null}

          <div className="h-[360px] rounded-2xl border border-slate-200 bg-white p-4">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={selectedDailySeries?.hours || []} margin={{ top: 16, right: 12, left: 8, bottom: 8 }}>
                <CartesianGrid stroke="#e2e8f0" strokeDasharray="3 3" />
                <XAxis dataKey="label" interval={1} minTickGap={16} />
                <YAxis allowDecimals={false} />
                <Tooltip content={<ClientTooltip clientMap={clientMap} />} />
                <Legend />
                {visibleClients.map((client) => (
                  <Line
                    key={client.id}
                    type="monotone"
                    dataKey={client.id}
                    name={client.label}
                    stroke={colorMap[client.id]}
                    strokeWidth={2.5}
                    dot={false}
                    activeDot={{ r: 5 }}
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      ) : null}

      {view === "weekly" ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {weeklySeries
            .filter((series) => !hiddenClientIds.includes(series.id))
            .map((series) => (
              <div key={series.id} className="rounded-2xl border border-slate-200 bg-white p-4">
                <div className="mb-3 flex items-center gap-2">
                  <span className="h-3 w-3 rounded-full" style={{ backgroundColor: colorMap[series.id] }} />
                  <span className="text-sm font-semibold text-slate-900">{series.label}</span>
                </div>
                <div className="h-[180px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={series.data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                      <CartesianGrid stroke="#e2e8f0" strokeDasharray="3 3" />
                      <XAxis
                        dataKey="xLabel"
                        tickFormatter={(value) => String(value).split(" ").slice(0, 2).join(" ")}
                        interval={23}
                        minTickGap={24}
                      />
                      <YAxis allowDecimals={false} width={28} />
                      <Tooltip
                        formatter={(value) => [value, series.label]}
                        labelFormatter={(value) => value}
                      />
                      <Line
                        type="monotone"
                        dataKey="count"
                        name={series.label}
                        stroke={colorMap[series.id]}
                        strokeWidth={2.5}
                        dot={false}
                        activeDot={{ r: 4 }}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>
            ))}
        </div>
      ) : null}

      {view === "monthly" ? (
        <div className="h-[380px] rounded-2xl border border-slate-200 bg-white p-4">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={monthlySeries} margin={{ top: 16, right: 12, left: 8, bottom: 8 }}>
              <CartesianGrid stroke="#e2e8f0" strokeDasharray="3 3" />
              <XAxis
                dataKey="xLabel"
                interval={7}
                minTickGap={20}
                tickFormatter={(value) => {
                  const parts = String(value).split(" ");
                  return `${parts[0]} ${parts[1] || ""}`.trim();
                }}
              />
              <YAxis allowDecimals={false} />
              <Tooltip content={<ClientTooltip clientMap={clientMap} />} />
              <Legend />
              {visibleClients.map((client) => (
                <Area
                  key={client.id}
                  type="monotone"
                  dataKey={client.id}
                  name={client.label}
                  stroke={colorMap[client.id]}
                  fill={colorMap[client.id]}
                  fillOpacity={0.16}
                  strokeWidth={2}
                />
              ))}
            </AreaChart>
          </ResponsiveContainer>
        </div>
      ) : null}
    </div>
  );
}
