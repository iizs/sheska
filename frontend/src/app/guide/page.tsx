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
        <h1>로컬 연동 가이드</h1>

        <h2>1. Git Clone / Pull (SC-24)</h2>
        <p>Wiki Store를 로컬에 복제하면 <code>_sheska.yaml</code>을 포함한 전체 위키를 받을 수 있습니다.</p>
        <pre className="bg-gray-100 rounded p-3 text-sm overflow-x-auto">{`# 최초 복제
git clone http://${host}/git/wiki-store.git

# 이후 업데이트
git -C wiki-store pull`}</pre>

        <h2>2. ZIP 다운로드 (SC-25)</h2>
        <p>
          Wiki 탭 상단의 <strong>ZIP 다운로드</strong> 버튼을 클릭하거나 아래 API를 직접 호출하세요.
        </p>
        <pre className="bg-gray-100 rounded p-3 text-sm overflow-x-auto">{`GET /api/wiki/zip
Authorization: Bearer <JWT>`}</pre>

        <h2>3. source_base_url 설정 (SC-26)</h2>
        <p>
          위키 루트의 <code>_sheska.yaml</code>에 <code>source_base_url</code>이 기록됩니다. 환경 변수로 설정하세요.
        </p>
        <pre className="bg-gray-100 rounded p-3 text-sm overflow-x-auto">{`# .env
SOURCE_BASE_URL=https://sheska.yourcompany.com/api/sources`}</pre>
        <p>
          위키 페이지 <code>sources</code> frontmatter의 파일명과 합쳐 원본 접근 URL이 됩니다.
        </p>
        <pre className="bg-gray-100 rounded p-3 text-sm overflow-x-auto">{`# 위키 페이지 frontmatter
sources:
  - "product_spec.pdf"

# 실제 접근 URL
https://sheska.yourcompany.com/api/sources/product_spec.pdf`}</pre>

        <h2>4. 에이전트 연동 프롬프트 예시</h2>
        <p>로컬에 복제한 위키를 LLM 에이전트에 연결할 때 사용하는 기본 프롬프트 예시입니다.</p>
        <pre className="bg-gray-100 rounded p-3 text-sm overflow-x-auto">{`당신은 팀 위키 어시스턴트입니다.
위키는 /path/to/wiki-store 에 Obsidian Markdown 형식으로 저장되어 있습니다.

시작 시:
1. index.md를 읽어 전체 위키 구조를 파악하세요.
2. _sheska.yaml에서 source_base_url을 확인하세요.
3. 질문에 답할 때 관련 페이지를 읽고 [[링크]]로 참조하세요.
4. 원본 파일이 필요하면 source_base_url + 파일명으로 접근하세요.`}</pre>
      </div>
    </div>
  );
}
