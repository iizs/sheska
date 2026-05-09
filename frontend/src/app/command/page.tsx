"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Nav from "@/components/Nav";
import { getMe, submitWikiCommand } from "@/lib/api";

export default function WikiCommandPage() {
  const router = useRouter();
  const [role, setRole] = useState("");
  const [command, setCommand] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem("sheska_token");
    if (!token) { router.push("/login"); return; }
    getMe().then((me) => setRole(me.role))
      .catch(() => router.push("/login"))
      .finally(() => setLoading(false));
  }, [router]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!command.trim()) return;
    setSubmitting(true);
    setMessage("");
    try {
      await submitWikiCommand(command);
      setMessage("Command queued. Redirecting to Jobs...");
      setCommand("");
      setTimeout(() => router.push("/jobs"), 800);
    } catch (err: any) {
      setMessage(`Error: ${err.message}`);
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) return <div className="p-8">Loading...</div>;

  return (
    <div className="min-h-screen">
      <Nav role={role} />
      <div className="max-w-3xl mx-auto p-6">
        <h1 className="text-2xl font-bold mb-2">Wiki Command</h1>
        <p className="text-sm text-gray-500 mb-6">
          Describe a multi-page change in natural language. The LLM will produce a Plan
          (create / merge_into / supersede / delete) and execute it.
        </p>

        <div className="bg-white border rounded-xl p-6">
          <form onSubmit={handleSubmit} className="space-y-3">
            <textarea
              value={command}
              onChange={(e) => setCommand(e.target.value)}
              rows={6}
              placeholder={'Examples:\n• Split the refund section out of [[checkout]] into [[refund-policy]]\n• Merge [[oauth]] and [[oauth2]] together\n• Delete [[deprecated-page]]'}
              className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none"
            />
            {message && (
              <p className={`text-sm ${message.startsWith("Error") ? "text-red-500" : "text-green-600"}`}>
                {message}
              </p>
            )}
            <div className="flex justify-between items-center">
              <p className="text-xs text-gray-400">
                Result will appear as a Job in the Jobs tab. The wiki is changed immediately;
                there is no approval step in this version.
              </p>
              <button
                type="submit"
                disabled={submitting || !command.trim()}
                className="bg-indigo-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
              >
                {submitting ? "Submitting..." : "Submit command"}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
