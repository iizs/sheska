"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Nav from "@/components/Nav";
import { getMe } from "@/lib/api";

export default function GuidePage() {
  const router = useRouter();
  const [role, setRole] = useState("");

  useEffect(() => {
    const token = localStorage.getItem("sheska_token");
    if (!token) { router.push("/login"); return; }
    getMe().then((me) => setRole(me.role)).catch(() => router.push("/login"));
  }, [router]);

  const host = typeof window !== "undefined" ? window.location.hostname : "sheska.yourcompany.com";

  return (
    <div className="min-h-screen">
      <Nav role={role} />
      <div className="max-w-3xl mx-auto p-6 prose prose-sm">
        <h1>Local Sync Guide</h1>

        <h2>1. Git Clone / Pull</h2>
        <p>Clone the wiki store locally to get the entire wiki, including <code>_sheska.yaml</code>.</p>
        <pre className="bg-gray-100 rounded p-3 text-sm overflow-x-auto">{`# Initial clone
git clone http://${host}/git/wiki-store.git

# Subsequent updates
git -C wiki-store pull`}</pre>

        <h2>2. ZIP Download</h2>
        <p>
          Click the <strong>Download ZIP</strong> button at the top of the Wiki tab, or call the API directly.
        </p>
        <pre className="bg-gray-100 rounded p-3 text-sm overflow-x-auto">{`GET /api/wiki/zip
Authorization: Bearer <JWT>`}</pre>

        <h2>3. source_base_url Setup</h2>
        <p>
          The <code>source_base_url</code> is recorded in <code>_sheska.yaml</code> at the wiki root.
          Set it via environment variable on the Sheska server.
        </p>
        <pre className="bg-gray-100 rounded p-3 text-sm overflow-x-auto">{`# .env on the Sheska server
SOURCE_BASE_URL=https://sheska.yourcompany.com/api/sources`}</pre>
        <p>
          A wiki page&apos;s <code>sources</code> frontmatter holds only the original filename. Combined with
          <code>source_base_url</code>, this yields the full access URL.
        </p>
        <pre className="bg-gray-100 rounded p-3 text-sm overflow-x-auto">{`# Wiki page frontmatter
sources:
  - "product_spec.pdf"

# Resolved access URL
https://sheska.yourcompany.com/api/sources/product_spec.pdf`}</pre>

        <h2>4. Network / CORS Setup</h2>
        <p>
          To access Sheska from another machine on your network (e.g.,{" "}
          <code>http://192.168.50.106:3000</code>):
        </p>
        <ol>
          <li>
            Bind <strong>uvicorn to all interfaces</strong>:
            <pre className="bg-gray-100 rounded p-3 text-sm overflow-x-auto">{`uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`}</pre>
          </li>
          <li>
            Add the <strong>browser-side origin</strong> to <code>ALLOWED_ORIGINS</code> in
            your <code>.env</code> (comma-separated):
            <pre className="bg-gray-100 rounded p-3 text-sm overflow-x-auto">{`ALLOWED_ORIGINS=http://localhost:3000,http://192.168.50.106:3000`}</pre>
          </li>
          <li>
            Update the frontend&apos;s <code>NEXT_PUBLIC_API_URL</code> in{" "}
            <code>frontend/.env.local</code> to the backend&apos;s LAN address:
            <pre className="bg-gray-100 rounded p-3 text-sm overflow-x-auto">{`NEXT_PUBLIC_API_URL=http://192.168.50.106:8000/api`}</pre>
          </li>
          <li>Restart both backend and frontend.</li>
        </ol>
        <p>
          ⚠️ Never use <code>ALLOWED_ORIGINS=*</code> in production — it disables CORS
          protection and lets any site call your backend with the user&apos;s credentials.
          Always list the specific origins you trust.
        </p>

        <h2>5. Tuning LLM Output Budget</h2>
        <p>
          If wiki commands or ingests frequently fail with <code>stop_reason=max_tokens</code>,
          raise the per-call output budget via <code>LLM_MAX_OUTPUT_TOKENS</code> in <code>.env</code>:
        </p>
        <pre className="bg-gray-100 rounded p-3 text-sm overflow-x-auto">{`LLM_MAX_OUTPUT_TOKENS=16384`}</pre>
        <p>
          Default is 8192. Sonnet 4.5 supports up to 64000 (extended beta). If a single page
          rewrite repeatedly hits the cap, you can also break the task into smaller patches
          (the agent already prefers <code>patch_page</code> for partial edits).
        </p>

        <h2>6. Agent Integration Prompt Example</h2>
        <p>An example prompt for connecting your locally cloned wiki to an LLM agent.</p>
        <pre className="bg-gray-100 rounded p-3 text-sm overflow-x-auto">{`You are a team wiki assistant.
The wiki lives at /path/to/wiki-store in Obsidian Markdown format.

On startup:
1. Read index.md to understand the wiki structure.
2. Check _sheska.yaml for the source_base_url.
3. When answering, read relevant pages and reference them with [[wikilinks]].
4. To access source files, fetch source_base_url + filename.`}</pre>
      </div>
    </div>
  );
}
