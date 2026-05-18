"use client";
import { useEffect, useState } from "react";
import { useRouter, useParams } from "next/navigation";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import wikiLinkPlugin from "remark-wiki-link";
import yaml from "js-yaml";
import Nav from "@/components/Nav";
import {
  getPage, getMe, requestEdit, downloadSource, listPages,
  createLintFinding, LINT_CATEGORIES, LintCategory,
} from "@/lib/api";

const PROPERTIES_STORAGE_KEY = "sheska_props_collapsed";

function slugifyPageName(name: string): string {
  // Match parser slugify in backend wiki_store.py
  return name
    .replace(/[^\p{L}\p{N}_-]+/gu, "-")
    .replace(/^-+|-+$/g, "")
    .toLowerCase();
}

function splitFrontmatter(content: string): { frontmatter: Record<string, any> | null; body: string } {
  const match = content.match(/^---\n([\s\S]*?)\n---\n?([\s\S]*)$/);
  if (!match) return { frontmatter: null, body: content };
  try {
    const fm = yaml.load(match[1]) as Record<string, any>;
    return { frontmatter: fm ?? {}, body: match[2] };
  } catch {
    return { frontmatter: null, body: content };
  }
}

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
  const [notFound, setNotFound] = useState(false);
  const [propsOpen, setPropsOpen] = useState(false);
  const [allPages, setAllPages] = useState<string[]>([]);
  const [reportOpen, setReportOpen] = useState(false);
  const [reportCategory, setReportCategory] = useState<LintCategory>("user_reported");
  const [reportDescription, setReportDescription] = useState("");
  const [reportSubmitting, setReportSubmitting] = useState(false);
  const [reportMessage, setReportMessage] = useState("");

  useEffect(() => {
    const token = localStorage.getItem("sheska_token");
    if (!token) { router.push("/login"); return; }
    if (typeof window !== "undefined") {
      const stored = localStorage.getItem(PROPERTIES_STORAGE_KEY);
      if (stored === "open") setPropsOpen(true);
    }
    Promise.all([
      getPage(pagePath).catch((e) => { setNotFound(true); return null; }),
      getMe(),
      listPages().catch(() => ({ pages: [] as string[] })),
    ])
      .then(([page, me, pages]) => {
        if (page) setContent(page.content);
        setRole(me.role);
        setAllPages(pages.pages);
      })
      .catch(() => router.push("/login"))
      .finally(() => setLoading(false));
  }, [pagePath, router]);

  function togglePropsOpen() {
    const next = !propsOpen;
    setPropsOpen(next);
    if (typeof window !== "undefined") {
      localStorage.setItem(PROPERTIES_STORAGE_KEY, next ? "open" : "closed");
    }
  }

  async function handleEditSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!editText.trim()) return;
    setSubmitting(true);
    setMessage("");
    try {
      await requestEdit(pagePath, editText);
      setMessage("Edit request queued.");
      setEditText("");
    } catch (err: any) {
      setMessage(`Error: ${err.message}`);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleReport(e: React.FormEvent) {
    e.preventDefault();
    if (!reportDescription.trim()) return;
    setReportSubmitting(true);
    setReportMessage("");
    try {
      await createLintFinding({
        page_path: pagePath,
        description: reportDescription,
        category: reportCategory,
      });
      setReportMessage("Reported. Thanks!");
      setReportDescription("");
      setTimeout(() => { setReportOpen(false); setReportMessage(""); }, 1500);
    } catch (err: any) {
      setReportMessage(`Error: ${err.message}`);
    } finally {
      setReportSubmitting(false);
    }
  }

  async function handleSourceDownload(filename: string) {
    try {
      const blob = await downloadSource(filename);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e: any) {
      setMessage(`Error: ${e.message}`);
    }
  }

  if (loading) return <div className="p-8">Loading...</div>;

  if (notFound) {
    return (
      <div className="min-h-screen">
        <Nav role={role} />
        <div className="max-w-3xl mx-auto p-6">
          <button
            onClick={() => router.push("/wiki")}
            className="text-sm text-gray-500 hover:text-gray-800 mb-4 inline-block"
          >
            ← Back to list
          </button>
          <div className="bg-white border rounded-xl p-8 text-center">
            <h1 className="text-xl font-bold mb-2">This page does not yet exist</h1>
            <p className="text-sm text-gray-500 mb-4">
              <span className="font-mono">{pagePath.replace(".md", "")}</span> has not been created.
              Pages are generated by the LLM from source documents — direct creation is not supported.
            </p>
            <Link href="/wiki" className="text-sm text-indigo-600 hover:underline">
              Browse existing pages
            </Link>
          </div>
        </div>
      </div>
    );
  }

  const { frontmatter, body } = splitFrontmatter(content);
  const pageSet = new Set(allPages.map((p) => p.replace(".md", "").toLowerCase()));

  return (
    <div className="min-h-screen">
      <Nav role={role} />
      <div className="max-w-3xl mx-auto p-6">
        <div className="flex items-center justify-between mb-4">
          <button
            onClick={() => router.push("/wiki")}
            className="text-sm text-gray-500 hover:text-gray-800 inline-block"
          >
            ← Back to list
          </button>
          <button
            onClick={() => setReportOpen(true)}
            className="text-xs text-gray-500 hover:text-red-600 underline"
            title="Report an issue with this page"
          >
            Report issue
          </button>
        </div>

        {reportOpen && (
          <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
            <div className="bg-white rounded-xl p-6 w-full max-w-md shadow-lg">
              <h2 className="text-lg font-semibold mb-3">Report an issue</h2>
              <p className="text-xs text-gray-500 mb-4">
                Page: <span className="font-mono">{pagePath}</span>
              </p>
              <form onSubmit={handleReport} className="space-y-3">
                <div>
                  <label className="block text-xs font-medium mb-1">Category</label>
                  <select
                    value={reportCategory}
                    onChange={(e) => setReportCategory(e.target.value as LintCategory)}
                    className="w-full border rounded px-2 py-1 text-sm"
                  >
                    {LINT_CATEGORIES.map((c) => (
                      <option key={c} value={c}>{c}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium mb-1">Description</label>
                  <textarea
                    value={reportDescription}
                    onChange={(e) => setReportDescription(e.target.value)}
                    rows={4}
                    placeholder="What is wrong with this page?"
                    className="w-full border rounded px-2 py-1 text-sm resize-none"
                    required
                  />
                </div>
                {reportMessage && (
                  <p className={`text-xs ${reportMessage.startsWith("Error") ? "text-red-500" : "text-green-600"}`}>
                    {reportMessage}
                  </p>
                )}
                <div className="flex justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => { setReportOpen(false); setReportMessage(""); }}
                    className="text-sm px-3 py-1.5 border rounded hover:bg-gray-50"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={reportSubmitting || !reportDescription.trim()}
                    className="text-sm px-3 py-1.5 bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50"
                  >
                    {reportSubmitting ? "Submitting..." : "Submit report"}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {/* SC-19: read-only body */}
        {/* SC-34: order = body → properties → edit */}
        <article className="bg-white border rounded-xl p-6 prose prose-sm max-w-none mb-4 select-text">
          <ReactMarkdown
            remarkPlugins={[
              [
                wikiLinkPlugin,
                {
                  pageResolver: (name: string) => [slugifyPageName(name)],
                  hrefTemplate: (permalink: string) => `/wiki/${permalink}.md`,
                  aliasDivider: "|",
                },
              ],
            ]}
            components={{
              a: ({ href, className, children, ...props }: any) => {
                if (className?.includes("internal")) {
                  // SC-20: wikilink rendered by remark-wiki-link
                  const slug = href?.replace(/^\/wiki\//, "").replace(/\.md$/, "").toLowerCase() ?? "";
                  const exists = pageSet.has(slug);
                  return (
                    <Link
                      href={href}
                      className={exists ? "text-indigo-600 hover:underline" : "text-red-500 hover:underline italic"}
                    >
                      {children}
                    </Link>
                  );
                }
                return <a href={href} {...props}>{children}</a>;
              },
            }}
          >
            {body}
          </ReactMarkdown>
        </article>

        {/* SC-33: page properties — collapsible, table form */}
        {frontmatter && Object.keys(frontmatter).length > 0 && (
          <details
            open={propsOpen}
            onToggle={(e) => {
              const open = (e.target as HTMLDetailsElement).open;
              setPropsOpen(open);
              if (typeof window !== "undefined") {
                localStorage.setItem(PROPERTIES_STORAGE_KEY, open ? "open" : "closed");
              }
            }}
            className="bg-white border rounded-xl mb-4"
          >
            <summary className="cursor-pointer select-none px-4 py-3 text-sm font-semibold text-gray-700">
              Page Properties
            </summary>
            <table className="w-full text-sm border-t">
              <tbody>
                {Object.entries(frontmatter).map(([key, value]) => (
                  <tr key={key} className="border-b last:border-b-0">
                    <td className="px-4 py-2 font-medium w-40 text-gray-600 align-top">{key}</td>
                    <td className="px-4 py-2">
                      <PropertyValue
                        keyName={key}
                        value={value}
                        onSourceClick={handleSourceDownload}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        )}

        {/* SC-15/SC-34: edit input at bottom */}
        <div className="bg-white border rounded-xl p-6">
          <h2 className="text-sm font-semibold text-gray-700 mb-3">Edit Request</h2>
          <form onSubmit={handleEditSubmit} className="space-y-3">
            <textarea
              value={editText}
              onChange={(e) => setEditText(e.target.value)}
              rows={4}
              placeholder="Describe what you want changed on this page..."
              className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none"
            />
            {message && (
              <p className={`text-sm ${message.startsWith("Error") ? "text-red-500" : "text-green-600"}`}>
                {message}
              </p>
            )}
            <button
              type="submit"
              disabled={submitting}
              className="bg-indigo-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
            >
              {submitting ? "Submitting..." : "Submit edit request"}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}

function PropertyValue({
  keyName,
  value,
  onSourceClick,
}: {
  keyName: string;
  value: any;
  onSourceClick: (filename: string) => void;
}) {
  if (value === null || value === undefined) return <span className="text-gray-400">—</span>;

  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="text-gray-400">—</span>;

    // SC-79: backlinks are clickable wikilinks
    if (keyName === "backlinks") {
      return (
        <span className="inline-flex flex-wrap gap-x-2 gap-y-1">
          {value.map((v, i) => {
            const stem = String(v);
            return (
              <Link
                key={i}
                href={`/wiki/${stem}.md`}
                className="text-indigo-600 hover:underline"
              >
                {stem}
              </Link>
            );
          })}
        </span>
      );
    }

    // SC-35: sources are clickable (download via fetch+blob)
    if (keyName === "sources") {
      return (
        <span className="inline-flex flex-wrap gap-x-2 gap-y-1">
          {value.map((v, i) => (
            <button
              key={i}
              type="button"
              onClick={() => onSourceClick(String(v))}
              className="text-indigo-600 hover:underline"
            >
              {String(v)}
            </button>
          ))}
        </span>
      );
    }

    return <span>{value.map((v) => String(v)).join(", ")}</span>;
  }

  return <span>{String(value)}</span>;
}
