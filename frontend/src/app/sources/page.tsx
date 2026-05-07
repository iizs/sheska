"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Nav from "@/components/Nav";
import { listSources, uploadSource, getMe, downloadSource } from "@/lib/api";

interface SourceFile { filename: string; size: number }

export default function SourcesPage() {
  const router = useRouter();
  const [sources, setSources] = useState<SourceFile[]>([]);
  const [role, setRole] = useState("");
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  async function reload() {
    const [data, me] = await Promise.all([listSources(), getMe()]);
    setSources(data);
    setRole(me.role);
  }

  useEffect(() => {
    const token = localStorage.getItem("sheska_token");
    if (!token) { router.push("/login"); return; }
    reload().catch(() => router.push("/login")).finally(() => setLoading(false));
  }, [router]);

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setError("");
    try {
      await uploadSource(file);
      await reload();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setUploading(false);
      e.target.value = "";
    }
  }

  async function handleDownload(filename: string) {
    setError("");
    try {
      const blob = await downloadSource(filename);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e: any) {
      setError(e.message);
    }
  }

  if (loading) return <div className="p-8">Loading...</div>;

  return (
    <div className="min-h-screen">
      <Nav role={role} />
      <div className="max-w-3xl mx-auto p-6">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold">Sources</h1>
          {role === "admin" && (
            <label className="cursor-pointer bg-indigo-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-indigo-700">
              {uploading ? "Uploading..." : "Upload file"}
              <input type="file" className="hidden" onChange={handleUpload} accept=".pdf,.txt,.md" disabled={uploading} />
            </label>
          )}
        </div>
        {error && <p className="text-red-500 text-sm mb-4">{error}</p>}
        {sources.length === 0 ? (
          <p className="text-gray-500">No source files uploaded yet.</p>
        ) : (
          <ul className="space-y-2">
            {sources.map((s) => (
              <li key={s.filename} className="bg-white border rounded-lg px-4 py-3 flex items-center justify-between">
                <span className="text-sm">{s.filename}</span>
                <div className="flex items-center gap-3">
                  <span className="text-xs text-gray-400">{(s.size / 1024).toFixed(1)} KB</span>
                  <button
                    onClick={() => handleDownload(s.filename)}
                    className="text-xs text-indigo-600 hover:underline"
                  >
                    Download
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
