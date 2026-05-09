"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Nav from "@/components/Nav";
import { listJobs, getMe } from "@/lib/api";

const STATUS_COLOR: Record<string, string> = {
  pending: "bg-yellow-100 text-yellow-800",
  processing: "bg-blue-100 text-blue-800",
  done: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
};

const PAGE_SIZE_OPTIONS = [20, 50, 100];

export default function JobsPage() {
  const router = useRouter();
  const [jobs, setJobs] = useState<any[]>([]);
  const [role, setRole] = useState("");
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [size, setSize] = useState(20);
  const [total, setTotal] = useState(0);

  async function reload(p = page, s = size) {
    const [data, me] = await Promise.all([listJobs(p, s), getMe()]);
    setJobs(data.items);
    setTotal(data.total);
    setRole(me.role);
  }

  useEffect(() => {
    const token = localStorage.getItem("sheska_token");
    if (!token) { router.push("/login"); return; }
    reload(page, size).catch(() => router.push("/login")).finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, size]);

  const totalPages = Math.max(1, Math.ceil(total / size));

  if (loading) return <div className="p-8">Loading...</div>;

  return (
    <div className="min-h-screen">
      <Nav role={role} />
      <div className="max-w-4xl mx-auto p-6">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold">Jobs</h1>
          <label className="text-sm text-gray-500 flex items-center gap-2">
            Page size:
            <select
              value={size}
              onChange={(e) => { setSize(Number(e.target.value)); setPage(1); }}
              className="border rounded px-2 py-1 text-sm"
            >
              {PAGE_SIZE_OPTIONS.map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </select>
          </label>
        </div>

        {jobs.length === 0 ? (
          <p className="text-gray-500">No jobs.</p>
        ) : (
          <>
            <div className="space-y-3">
              {jobs.map((job) => (
                <div key={job.id} className="bg-white border rounded-xl p-4">
                  <div className="flex items-start justify-between">
                    <div>
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-xs font-semibold uppercase text-gray-500">{job.type}</span>
                        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${STATUS_COLOR[job.status] ?? ""}`}>
                          {job.status}
                        </span>
                      </div>
                      <p className="text-xs text-gray-400 font-mono">{job.id}</p>
                    </div>
                  </div>

                  {job.payload?.page_path && (
                    <p className="text-sm mt-2">
                      <span className="font-medium">Target:</span> {job.payload.page_path}
                    </p>
                  )}
                  {job.payload?.source_path && (
                    <p className="text-sm mt-2">
                      <span className="font-medium">Source:</span> {job.payload.source_path}
                    </p>
                  )}
                  {job.payload?.edit_text && (
                    <p className="text-sm mt-1 text-gray-600 truncate">
                      <span className="font-medium">Request:</span> {job.payload.edit_text}
                    </p>
                  )}
                  {job.payload?.command_text && (
                    <p className="text-sm mt-1 text-gray-600">
                      <span className="font-medium">Command:</span> {job.payload.command_text}
                    </p>
                  )}
                  {Array.isArray(job.payload?.plan_summary) && job.payload.plan_summary.length > 0 && (
                    <details className="mt-2">
                      <summary className="text-xs text-gray-500 cursor-pointer">
                        Plan: {job.payload.plan_summary.length} action(s)
                      </summary>
                      <ul className="text-xs mt-1 space-y-0.5">
                        {job.payload.plan_summary.map((s: any, i: number) => (
                          <li key={i} className="font-mono">
                            <span className="text-gray-500">{s.outcome}</span>{" "}
                            <span className="text-gray-700">{s.action}</span>
                            {s.info?.target && <> → {s.info.target}</>}
                            {s.info?.page_path && <> → {s.info.page_path}</>}
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                  {job.error_msg && (
                    <p className="text-sm mt-1 text-red-500">
                      <span className="font-medium">Error:</span> {job.error_msg}
                    </p>
                  )}
                </div>
              ))}
            </div>

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
          </>
        )}
      </div>
    </div>
  );
}
