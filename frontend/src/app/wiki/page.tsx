"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import Nav from "@/components/Nav";
import { listPages, getMe, downloadZip } from "@/lib/api";

export default function WikiListPage() {
  const router = useRouter();
  const [pages, setPages] = useState<string[]>([]);
  const [role, setRole] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem("sheska_token");
    if (!token) { router.push("/login"); return; }
    Promise.all([listPages(), getMe()])
      .then(([pagesData, me]) => {
        setPages(pagesData.pages);
        setRole(me.role);
      })
      .catch(() => router.push("/login"))
      .finally(() => setLoading(false));
  }, [router]);

  async function handleZipDownload() {
    const blob = await downloadZip();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "wiki.zip";
    a.click();
    URL.revokeObjectURL(url);
  }

  if (loading) return <div className="p-8">Loading...</div>;

  return (
    <div className="min-h-screen">
      <Nav role={role} />
      <div className="max-w-3xl mx-auto p-6">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold">Wiki</h1>
          <button
            onClick={handleZipDownload}
            className="text-sm bg-gray-100 hover:bg-gray-200 px-3 py-1.5 rounded-lg"
          >
            Download ZIP
          </button>
        </div>
        {pages.length === 0 ? (
          <p className="text-gray-500">No wiki pages yet.</p>
        ) : (
          <ul className="space-y-2">
            {pages.map((p) => (
              <li key={p}>
                <Link
                  href={`/wiki/${p}`}
                  className="block bg-white border rounded-lg px-4 py-3 hover:border-indigo-400 hover:shadow-sm transition"
                >
                  {p.replace(".md", "")}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
