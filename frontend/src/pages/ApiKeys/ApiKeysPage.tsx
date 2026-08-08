import { useState } from "react";

import {
  useApiKeys,
  useCreateApiKey,
  useRevokeApiKey,
  useUsers,
  type ApiKeyCreated,
} from "../../hooks/useApiKeys";

const inputClass =
  "bg-slate-900 border border-slate-700 rounded-md px-2 py-1.5 text-sm text-slate-100 w-full";

function statusOf(key: { revoked_at: string | null; expires_at: string | null }): {
  label: string;
  tone: "active" | "revoked" | "expired";
} {
  if (key.revoked_at) return { label: "Revoked", tone: "revoked" };
  if (key.expires_at && new Date(key.expires_at) <= new Date()) {
    return { label: "Expired", tone: "expired" };
  }
  return { label: "Active", tone: "active" };
}

const toneClass: Record<string, string> = {
  active: "text-emerald-400",
  revoked: "text-slate-500",
  expired: "text-amber-400",
};

export function ApiKeysPage() {
  const { data: users } = useUsers();
  const [userId, setUserId] = useState<string>("");
  const { data: keys } = useApiKeys(userId || undefined);
  const createKey = useCreateApiKey();
  const revokeKey = useRevokeApiKey(userId || undefined);

  const [name, setName] = useState("");
  const [expiresAt, setExpiresAt] = useState("");
  const [justCreated, setJustCreated] = useState<ApiKeyCreated | null>(null);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!userId || !name.trim()) return;
    const created = await createKey.mutateAsync({
      userId,
      name: name.trim(),
      expiresAt: expiresAt ? new Date(expiresAt).toISOString() : undefined,
    });
    setJustCreated(created);
    setName("");
    setExpiresAt("");
  }

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h2 className="text-sm uppercase tracking-wide text-slate-500 mb-2">
          Service accounts &amp; API keys
        </h2>
        <p className="text-sm text-slate-500 mb-3">
          Machine-to-machine credentials for BI/pipeline tools (Fabric, Power BI, Databricks, …)
          calling the REST export endpoints instead of connecting directly to Postgres. See{" "}
          <code className="text-slate-400">INTEGRATIONS.md</code>. Provision a VIEWER user for the
          integration first (Register on the login page, or ask an admin), then pick it below.
        </p>
        <label className="text-xs text-slate-400">Service account user</label>
        <select
          className={inputClass}
          value={userId}
          onChange={(e) => {
            setUserId(e.target.value);
            setJustCreated(null);
          }}
        >
          <option value="">Select a user…</option>
          {users?.map((u) => (
            <option key={u.id} value={u.id}>
              {u.username} ({u.role})
            </option>
          ))}
        </select>
      </div>

      {userId && (
        <>
          {justCreated && (
            <div className="bg-emerald-950/40 border border-emerald-800 rounded-lg p-4">
              <p className="text-sm text-emerald-300 font-medium mb-1">
                Key created — copy it now, it won't be shown again
              </p>
              <code className="block text-xs bg-slate-950 rounded p-2 text-emerald-200 break-all">
                {justCreated.api_key}
              </code>
            </div>
          )}

          <form
            onSubmit={handleCreate}
            className="flex flex-wrap items-end gap-3 bg-slate-900/50 p-4 rounded-lg border border-slate-800"
          >
            <div>
              <label className="text-xs text-slate-400">Key name</label>
              <input
                className={inputClass}
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Fabric pipeline"
                required
              />
            </div>
            <div>
              <label className="text-xs text-slate-400">Expires (optional)</label>
              <input
                type="date"
                className={inputClass}
                value={expiresAt}
                onChange={(e) => setExpiresAt(e.target.value)}
              />
            </div>
            <button
              type="submit"
              disabled={createKey.isPending}
              className="bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium px-4 py-1.5 rounded-md disabled:opacity-50"
            >
              {createKey.isPending ? "Creating…" : "Create key"}
            </button>
            {createKey.isError && (
              <span className="text-sm text-red-400">Failed to create key.</span>
            )}
          </form>

          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-slate-500 border-b border-slate-800">
                <th className="py-1.5">Name</th>
                <th className="py-1.5">Prefix</th>
                <th className="py-1.5">Status</th>
                <th className="py-1.5">Last used</th>
                <th className="py-1.5">Expires</th>
                <th className="py-1.5"></th>
              </tr>
            </thead>
            <tbody>
              {keys?.map((key) => {
                const status = statusOf(key);
                return (
                  <tr key={key.id} className="border-b border-slate-900">
                    <td className="py-1.5">{key.name}</td>
                    <td className="py-1.5 font-mono text-xs text-slate-400">{key.key_prefix}…</td>
                    <td className={`py-1.5 ${toneClass[status.tone]}`}>{status.label}</td>
                    <td className="py-1.5 text-slate-400">
                      {key.last_used_at ? new Date(key.last_used_at).toLocaleString() : "Never"}
                    </td>
                    <td className="py-1.5 text-slate-400">
                      {key.expires_at ? new Date(key.expires_at).toLocaleDateString() : "—"}
                    </td>
                    <td className="py-1.5 text-right">
                      {status.tone === "active" && (
                        <button
                          className="bg-red-700 hover:bg-red-600 text-white text-xs font-medium px-3 py-1 rounded-md disabled:opacity-50"
                          disabled={revokeKey.isPending}
                          onClick={() => revokeKey.mutate(key.id)}
                        >
                          Revoke
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
              {keys?.length === 0 && (
                <tr>
                  <td colSpan={6} className="py-3 text-slate-500">
                    No API keys for this user yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
