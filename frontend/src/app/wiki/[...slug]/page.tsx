"use client";
import { useEffect, useState } from "react";
import { useRouter, useParams } from "next/navigation";
import ReactMarkdown from "react-markdown";
import Nav from "@/components/Nav";
import { getPage, getMe, requestEdit } from "@/lib/api";

export default function WikiPageView() {
  const router = useRouter();
  const params = useParams();
  const slug = Array.isArray(params.slug) ? params.slug.join("/") : params.slug ?? "";
  const pagePath = slug.endsWith(".md") ? slug : `${slug}.md`;

  const [content, setContent] = useState("");
  const [role, setRole] = useState("");
  const [editText, setEditText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem("sheska_token");
    if (!token) { router.push("/login"); return; }
    Promise.all([getPage(pagePath), getMe()])
      .then(([page, me]) => {
        setContent(page.content);
        setRole(me.role);
      })
      .catch(() => router.push("/wiki"))
      .finally(() => setLoading(false));
  }, [pagePath, router]);

  async function handleEditSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!editText.trim()) return;
    setSubmitting(true);
    setMessage("");
    try {
      await requestEdit(pagePath, editText);
      setMessage("수정 요청이 큐에 등록되었습니다.");
      setEditText("");
    } catch (err: any) {
      setMessage(`오류: ${err.message}`);
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) return <div className="p-8">Loading...</div>;

  return (
    <div className="min-h-screen">
      <Nav role={role} />
      <div className="max-w-3xl mx-auto p-6">
        <button
          onClick={() => router.push("/wiki")}
          className="text-sm text-gray-500 hover:text-gray-800 mb-4 inline-block"
        >
          ← 목록으로
        </button>

        {/* SC-19: 읽기 전용 — 직접 편집 불가 */}
        <div className="bg-white border rounded-xl p-6 prose prose-sm max-w-none mb-8 select-text">
          <ReactMarkdown>{content}</ReactMarkdown>
        </div>

        {/* SC-15/SC-20: 페이지 하단 수정 요청 입력창 */}
        <div className="bg-white border rounded-xl p-6">
          <h2 className="text-sm font-semibold text-gray-700 mb-3">수정 요청</h2>
          <form onSubmit={handleEditSubmit} className="space-y-3">
            <textarea
              value={editText}
              onChange={(e) => setEditText(e.target.value)}
              rows={4}
              placeholder="이 페이지에 대한 수정 요청을 입력하세요..."
              className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none"
            />
            {message && (
              <p className={`text-sm ${message.startsWith("오류") ? "text-red-500" : "text-green-600"}`}>
                {message}
              </p>
            )}
            <button
              type="submit"
              disabled={submitting}
              className="bg-indigo-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
            >
              {submitting ? "제출 중..." : "수정 요청 제출"}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
