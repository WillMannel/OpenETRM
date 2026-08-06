import { useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { useCurve, useBuildCurve } from "../../hooks/useCurve";
import { useSelection } from "../../hooks/useSelection";

export function CurveViewerPage() {
  const { asOfDate } = useSelection();
  const buildCurve = useBuildCurve();
  const [curveId, setCurveId] = useState<string | undefined>(undefined);
  const { data: curve, isLoading } = useCurve(curveId);

  const chartData = curve?.points.map((p) => ({ month: p.tenor_bucket, price: p.price })) ?? [];

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <button
          className="bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium px-4 py-1.5 rounded-md disabled:opacity-50"
          disabled={buildCurve.isPending}
          onClick={async () => {
            const built = await buildCurve.mutateAsync(asOfDate);
            setCurveId(built.id);
          }}
        >
          {buildCurve.isPending ? "Building…" : `Build curve as of ${asOfDate}`}
        </button>
        {buildCurve.isError && (
          <span className="text-sm text-red-400">
            Build failed — seed some market data quotes for this date first.
          </span>
        )}
      </div>

      {curve && (
        <>
          <div className="bg-slate-900/50 border border-slate-800 rounded-lg p-4" style={{ height: 300 }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis dataKey="month" stroke="#64748b" fontSize={12} />
                <YAxis stroke="#64748b" fontSize={12} domain={["auto", "auto"]} />
                <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #334155" }} />
                <Line type="stepAfter" dataKey="price" stroke="#34d399" strokeWidth={2} dot={{ r: 3 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>

          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-slate-500 border-b border-slate-800">
                <th className="py-1.5">Tenor</th>
                <th className="py-1.5">Delivery month</th>
                <th className="py-1.5">Price ($/MMBtu)</th>
              </tr>
            </thead>
            <tbody>
              {curve.points.map((p) => (
                <tr key={p.tenor_bucket} className="border-b border-slate-900">
                  <td className="py-1.5">{p.tenor_bucket}</td>
                  <td className="py-1.5">{p.delivery_month}</td>
                  <td className="py-1.5">${p.price.toFixed(3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      {!curve && !isLoading && (
        <p className="text-sm text-slate-500">
          No curve loaded yet. Seed market data quotes (via the API) for {asOfDate}, then build the curve above.
        </p>
      )}
    </div>
  );
}
