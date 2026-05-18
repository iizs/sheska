"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import Nav from "@/components/Nav";
import {
  getMe,
  listLintFindings,
  decideLintFinding,
  LINT_CATEGORIES,
  LintFinding,
  LintStatus,
  LintCategory,
} from "@/lib/api";

const STATUS_COLOR: Record<LintStatus, string> = {
  open: "bg-yellow-100 text-yellow-800",
  acknowledged: "bg-blue-100 text-blue-800",
  wont_fix: "bg-gray-200 text-gray-700",
};

const SIZE_OPTIONS = [20, 50, 100];

export default function LintPage() {
  const router = useRouter();
  const [role, setRole] = useState("");
  const [loading, setLoading] = useState(true);
  const [findings, setFindings] = useState<LintFinding[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [size, setSize] = useState(20);
  const [statusFilter, setStatusFilter] = useState<LintStatus | "">("open");
  const [categoryFilter, setCategoryFilter] = useState<LintCategory | "">("");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [actionError, setActionError] = useState("");

  async function reload(p = page, s = size) {
    const data = await listLintFindings({
      status: statusFilter || undefined,
      category: categoryFilter || undefined,
      page: p,
      size: s,
    });
    setFindings(data.items);
    setTotal(data.total);
  }

  useEffect(() => {
    const token = localStorage.getItem("sheska_token");
    if (!token) { router.push("/login"); return; }
    Promise.all([getMe()])
      .then(([me]) => setRole(me.role))
      .catch(() => router.push("/login"))
      .finally(() => setLoading(false));
  }, [router]);

  useEffect(() => {
    if (loading) return;
    reload(page, size).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, size, statusFilter, categoryFilter, loading]);

  async function decide(findingId: string, status: "acknowledged" | "wont_fix") {
    setActionError("");
    if (!reason.trim()) {
      setActionError("Reason is required.");
      return;
    }
    try {
      await decideLintFinding(findingId, status, reason);
      setReason("");
      setExpanded(null);
      await reload();
    } catch (e: any) {
      setActionError(e.message ?? "Failed");
    }
  }

  if (loading) return <div className="p-8">Loading...</div>;

  const totalPages = Math.max(1, Math.ceil(total / size));
  const isAdmin = role === "admin";

  return (
    <div className="min-h-screen">
      <Nav role={role} />
      <div className="max-w-5xl mx-auto p-6">
        <h1 className="text-2xl font-bold mb-6">Lint Findings</h1>

        <div className="flex items-center gap-3 mb-4 text-sm">
          <label className="text-gray-600">Status</label>
          <select
            value={statusFilter}
            onChange={(e) => { setStatusFilter(e.target.value as any); setPage(1); }}
            className="border rounded px-2 py-1"
          >
            <option value="">All</option>
            <option value="open">open</option>
            <option value="acknowledged">acknowledged</option>
            <option value="wont_fix">wont_fix</option>
          </select>

          <label className="text-gray-600 ml-2">Category</label>
          <select
            value={categoryFilter}
            onChange={(e) => { setCategoryFilter(e.target.value as any); setPage(1); }}
            className="border rounded px-2 py-1"
          >
            <option value="">All</option>
            {LINT_CATEGORIES.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>

          <label className="text-gray-600 ml-auto">Page size</label>
          <select
            value={size}
            onChange={(e) => { setSize(Number(e.target.value)); setPage(1); }}
            className="border rounded px-2 py-1"
          >
            {SIZE_OPTIONS.map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
        </div>

        {findings.length === 0 ? (
          <p className="text-gray-500">No findings.</p>
        ) : (
          <div className="space-y-2">
            {findings.map((f) => {
              const isOpen = expanded === f.finding_id;
              return (
                <div key={f.finding_id} className="bg-white border rounded-xl">
                  <button
                    onClick={() => { setExpanded(isOpen ? null : f.finding_id); setReason(""); setActionError(""); }}
                    className="w-full text-left p-4 hover:bg-gray-50"
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${STATUS_COLOR[f.status]}`}>
                        {f.status}
                      </span>
                      <span className="text-xs text-gray-500 uppercase">{f.category}</span>
                      <span className="text-xs text-gray-400 ml-auto">{new Date(f.created_at).toLocaleString()}</span>
                    </div>
                    <p className="text-sm">{f.description}</p>
                    {f.page_path && (
                      <p className="text-xs text-gray-500 mt-1">
                        Page:{" "}
                        <Link href={`/wiki/${f.page_path}`} className="text-indigo-600 hover:underline" onClick={(e) => e.stopPropagation()}>
                          {f.page_path}
                        </Link>
                      </p>
                    )}
                  </button>

                  {isOpen && (
                    <div className="border-t p-4 text-sm space-y-2">
                      <div className="text-xs text-gray-500">
                        Reported by <span className="font-medium">{f.reported_by}</span>{" "}
                        ({f.source})
                      </div>
                      {f.decided_by && (
                        <div className="text-xs text-gray-500">
                          Decided by <span className="font-medium">{f.decided_by}</span> at{" "}
                          {f.decided_at && new Date(f.decided_at).toLocaleString()} — {f.resolution_reason}
                        </div>
                      )}
                      {f.details && Object.keys(f.details).length > 0 && (
                        <pre className="text-xs bg-gray-50 rounded p-2 overflow-x-auto">
                          {JSON.stringify(f.details, null, 2)}
                        </pre>
                      )}

                      {f.status === "open" && isAdmin && (
                        <div className="space-y-2 mt-2">
                          <textarea
                            value={reason}
                            onChange={(e) => setReason(e.target.value)}
                            rows={2}
                            placeholder="Reason (required)"
                            className="w-full border rounded px-2 py-1 text-sm resize-none"
                          />
                          {actionError && <p className="text-red-500 text-xs">{actionError}</p>}
                          <div className="flex gap-2">
                            <button
                              onClick={() => decide(f.finding_id, "acknowledged")}
                              className="bg-indigo-600 text-white px-3 py-1 rounded text-xs font-medium hover:bg-indigo-700"
                            >
                              Acknowledge
                            </button>
                            <button
                              onClick={() => decide(f.finding_id, "wont_fix")}
                              className="border px-3 py-1 rounded text-xs hover:bg-gray-50"
                            >
                              Won&apos;t fix
                            </button>
                          </div>
                        </div>
                      )}
                      {f.status === "open" && !isAdmin && (
                        <p className="text-xs text-gray-400 italic">
                          Only an admin can change this status.
                        </p>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {findings.length > 0 && (
          <div className="flex items-center justify-between mt-6 text-sm">
            <span className="text-gray-500">Page {page} of {totalPages} · {total} total</span>
            <div className="flex gap-2">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
                className="px-3 py-1 border rounded disabled:opacity-40"
              >
                Prev
              </button>
              <button
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages}
                className="px-3 py-1 border rounded disabled:opacity-40"
              >
                Next
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
