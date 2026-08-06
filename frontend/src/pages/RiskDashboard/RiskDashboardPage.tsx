import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { useBookPnl } from "../../hooks/usePositions";
import { useDeltaLadder, useRunVar } from "../../hooks/useRisk";
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

export function RiskDashboardPage() {
  const { bookId, asOfDate } = useSelection();
  const pnl = useBookPnl(bookId, asOfDate);
  const ladder = useDeltaLadder(bookId, asOfDate);
  const runVar = useRunVar();

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
          value={`$${totalPnl.toLocaleString(undefined, { maximumFractionDigits: 0 })}`}
          tone={totalPnl >= 0 ? "positive" : "negative"}
        />
        <div className="bg-slate-900/50 border border-slate-800 rounded-lg p-4">
          <div className="text-xs uppercase tracking-wide text-slate-500">1-day VaR</div>
          <button
            className="mt-2 bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium px-3 py-1 rounded-md disabled:opacity-50"
            disabled={runVar.isPending}
            onClick={() => runVar.mutate({ bookId, asOfDate, confidenceLevel: 95 })}
          >
            {runVar.isPending ? "Running…" : "Run 95% VaR"}
          </button>
          {runVar.data && (
            <div className="text-2xl font-semibold mt-2">
              ${runVar.data.var_value.toLocaleString(undefined, { maximumFractionDigits: 0 })}
            </div>
          )}
        </div>
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
