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

        <h2>4. Agent Integration Prompt Example</h2>
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
