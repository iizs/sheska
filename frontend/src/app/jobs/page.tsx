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

export default function JobsPage() {
  const router = useRouter();
  const [jobs, setJobs] = useState<any[]>([]);
  const [role, setRole] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem("sheska_token");
    if (!token) { router.push("/login"); return; }
    Promise.all([listJobs(), getMe()])
      .then(([data, me]) => { setJobs(data); setRole(me.role); })
      .catch(() => router.push("/login"))
      .finally(() => setLoading(false));
  }, [router]);

  if (loading) return <div className="p-8">Loading...</div>;

  return (
    <div className="min-h-screen">
      <Nav role={role} />
      <div className="max-w-4xl mx-auto p-6">
        <h1 className="text-2xl font-bold mb-6">Jobs</h1>
        {jobs.length === 0 ? (
          <p className="text-gray-500">등록된 Job이 없습니다.</p>
        ) : (
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

                {/* SC-17-c: 수정된 페이지 표시 */}
                {job.payload?.page_path && (
                  <p className="text-sm mt-2">
                    <span className="font-medium">대상:</span> {job.payload.page_path}
                  </p>
                )}
                {job.payload?.source_path && (
                  <p className="text-sm mt-2">
                    <span className="font-medium">원본:</span> {job.payload.source_path}
                  </p>
                )}
                {job.payload?.edit_text && (
                  <p className="text-sm mt-1 text-gray-600 truncate">
                    <span className="font-medium">요청:</span> {job.payload.edit_text}
                  </p>
                )}
                {job.error_msg && (
                  <p className="text-sm mt-1 text-red-500">
                    <span className="font-medium">오류:</span> {job.error_msg}
                  </p>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
