import { useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { RoleGate } from "../../components/auth/RoleGate";
import { useBookPnl } from "../../hooks/usePositions";
import {
  useDeltaLadder,
  useRunPnlAttribution,
  useRunStressTest,
  useRunVar,
  type VarMethod,
} from "../../hooks/useRisk";
import { useSelection } from "../../hooks/useSelection";

function StatTile({ label, value, tone }: { label: string; value: string; tone?: "positive" | "negative" }) {
  const toneClass = tone === "positive" ? "text-emerald-400" : tone === "negative" ? "text-red-400" : "text-slate-100";
  return (
    <div className="bg-slate-900/50 border border-slate-800 rounded-lg p-4">
      <div className="text-xs uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`text-2xl font-semibold mt-1 ${toneClass}`}>{value}</div>
    </div>
  );
}

const money = (v: number) => `$${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;

export function RiskDashboardPage() {
  const { bookId, asOfDate, commodity } = useSelection();
  const pnl = useBookPnl(bookId, asOfDate, commodity);
  const ladder = useDeltaLadder(bookId, asOfDate, commodity);
  const runVar = useRunVar();
  const runStressTest = useRunStressTest();
  const runPnlAttribution = useRunPnlAttribution();
  const [varMethod, setVarMethod] = useState<VarMethod>("HISTORICAL_SIM");
  const [priorDate, setPriorDate] = useState("");

  if (!bookId) {
    return <p className="text-sm text-slate-500">Select a book above to see its risk dashboard.</p>;
  }

  const totalPnl = pnl.data?.total_unrealized_pnl ?? 0;
  const chartData = ladder.data?.buckets.map((b) => ({ bucket: b.tenor_bucket, delta: b.delta_value })) ?? [];

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <StatTile
          label="Unrealized P&L"
          value={money(totalPnl)}
          tone={totalPnl >= 0 ? "positive" : "negative"}
        />
        <RoleGate roles={["RISK_MANAGER", "ADMIN"]}>
          <div className="bg-slate-900/50 border border-slate-800 rounded-lg p-4">
            <div className="text-xs uppercase tracking-wide text-slate-500">VaR</div>
            <div className="flex items-center gap-2 mt-2">
              <select
                className="bg-slate-800 border border-slate-700 rounded-md px-2 py-1 text-xs text-slate-100"
                value={varMethod}
                onChange={(e) => setVarMethod(e.target.value as VarMethod)}
              >
                <option value="HISTORICAL_SIM">Historical sim</option>
                <option value="PARAMETRIC">Parametric</option>
                <option value="MONTE_CARLO">Monte Carlo</option>
              </select>
              <button
                className="bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium px-3 py-1 rounded-md disabled:opacity-50"
                disabled={runVar.isPending}
                onClick={() =>
                  runVar.mutate({ bookId, asOfDate, commodity, confidenceLevel: 95, method: varMethod })
                }
              >
                {runVar.isPending ? "Running…" : "Run"}
              </button>
            </div>
            {runVar.data && <div className="text-2xl font-semibold mt-2">{money(runVar.data.var_value)}</div>}
          </div>
        </RoleGate>
        <StatTile label="As of" value={asOfDate} />
      </div>

      <div>
        <h2 className="text-sm uppercase tracking-wide text-slate-500 mb-2">Delta ladder (bucketed by delivery month)</h2>
        <div className="bg-slate-900/50 border border-slate-800 rounded-lg p-4" style={{ height: 280 }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="bucket" stroke="#64748b" fontSize={12} />
              <YAxis stroke="#64748b" fontSize={12} />
              <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #334155" }} />
              <Bar dataKey="delta" fill="#38bdf8" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <RoleGate roles={["RISK_MANAGER", "ADMIN"]}>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="bg-slate-900/50 border border-slate-800 rounded-lg p-4">
            <div className="flex items-center justify-between">
              <h2 className="text-sm uppercase tracking-wide text-slate-500">Stress test</h2>
              <button
                className="bg-slate-700 hover:bg-slate-600 text-xs px-3 py-1 rounded-md disabled:opacity-50"
                disabled={runStressTest.isPending}
                onClick={() => runStressTest.mutate({ bookId, asOfDate, commodity })}
              >
                {runStressTest.isPending ? "Running…" : "Run default scenarios"}
              </button>
            </div>
            {runStressTest.data && (
              <table className="w-full text-sm mt-3">
                <tbody>
                  {runStressTest.data.results.map((r) => (
                    <tr key={r.scenario_name} className="border-b border-slate-900">
                      <td className="py-1.5 text-slate-400">{r.scenario_name}</td>
                      <td className={`py-1.5 text-right ${r.pnl_impact >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                        {money(r.pnl_impact)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div className="bg-slate-900/50 border border-slate-800 rounded-lg p-4">
            <h2 className="text-sm uppercase tracking-wide text-slate-500">P&L attribution</h2>
            <div className="flex items-center gap-2 mt-2">
              <input
                type="date"
                className="bg-slate-800 border border-slate-700 rounded-md px-2 py-1 text-xs text-slate-100"
                value={priorDate}
                onChange={(e) => setPriorDate(e.target.value)}
                placeholder="Prior date"
              />
              <span className="text-xs text-slate-500">→ {asOfDate}</span>
              <button
                className="bg-slate-700 hover:bg-slate-600 text-xs px-3 py-1 rounded-md disabled:opacity-50"
                disabled={runPnlAttribution.isPending || !priorDate}
                onClick={() =>
                  runPnlAttribution.mutate({ bookId, priorDate, currentDate: asOfDate, commodity })
                }
              >
                {runPnlAttribution.isPending ? "Running…" : "Run"}
              </button>
            </div>
            {runPnlAttribution.data && (
              <dl className="mt-3 text-sm space-y-1">
                <div className="flex justify-between">
                  <dt className="text-slate-400">Price effect</dt>
                  <dd>{money(runPnlAttribution.data.price_effect)}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-slate-400">New trade effect</dt>
                  <dd>{money(runPnlAttribution.data.new_trade_effect)}</dd>
                </div>
                <div className="flex justify-between font-semibold border-t border-slate-800 pt-1">
                  <dt>Total</dt>
                  <dd>{money(runPnlAttribution.data.total)}</dd>
                </div>
              </dl>
            )}
          </div>
        </div>
      </RoleGate>

      <div>
        <h2 className="text-sm uppercase tracking-wide text-slate-500 mb-2">Positions by delivery month</h2>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-slate-500 border-b border-slate-800">
              <th className="py-1.5">Delivery month</th>
              <th className="py-1.5">Net volume</th>
              <th className="py-1.5">Avg fixed price</th>
            </tr>
          </thead>
          <tbody>
            {pnl.data?.positions.map((p) => (
              <tr key={p.delivery_month} className="border-b border-slate-900">
                <td className="py-1.5">{p.delivery_month}</td>
                <td className="py-1.5">{p.net_volume.toLocaleString()}</td>
                <td className="py-1.5">${p.avg_fixed_price.toFixed(3)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
