"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { clearToken } from "@/lib/api";

export default function Nav({ role }: { role: string }) {
  const router = useRouter();

  function logout() {
    clearToken();
    router.push("/login");
  }

  return (
    <nav className="bg-white border-b px-6 py-3 flex items-center gap-6 text-sm font-medium">
      <span className="text-lg font-bold text-indigo-600">Sheska</span>
      <Link href="/wiki" className="hover:text-indigo-600">Wiki</Link>
      <Link href="/command" className="hover:text-indigo-600">Command</Link>
      <Link href="/sources" className="hover:text-indigo-600">Sources</Link>
      <Link href="/jobs" className="hover:text-indigo-600">Jobs</Link>
      <Link href="/guide" className="hover:text-indigo-600">Guide</Link>
      {role === "admin" && (
        <Link href="/admin/users" className="hover:text-indigo-600">Users</Link>
      )}
      <div className="ml-auto flex items-center gap-4">
        <span className="text-gray-500 text-xs uppercase">{role}</span>
        <button onClick={logout} className="text-gray-500 hover:text-red-500">Logout</button>
      </div>
    </nav>
  );
}
