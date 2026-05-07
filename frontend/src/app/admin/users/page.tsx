"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Nav from "@/components/Nav";
import { listUsers, getMe, updateUserRole, updateUserActive } from "@/lib/api";

interface UserRow {
  id: number;
  email: string;
  role: "admin" | "member";
  is_active: boolean;
  created_at: string | null;
}

export default function AdminUsersPage() {
  const router = useRouter();
  const [users, setUsers] = useState<UserRow[]>([]);
  const [me, setMe] = useState<{ id: number; role: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function reload() {
    const [list, current] = await Promise.all([listUsers(), getMe()]);
    setUsers(list);
    setMe({ id: current.id, role: current.role });
  }

  useEffect(() => {
    const token = localStorage.getItem("sheska_token");
    if (!token) { router.push("/login"); return; }
    reload()
      .catch((e) => {
        if (e.message?.includes("Admin")) router.push("/wiki");
        else router.push("/login");
      })
      .finally(() => setLoading(false));
  }, [router]);

  async function handleRole(user: UserRow, newRole: "admin" | "member") {
    setError("");
    try {
      await updateUserRole(user.id, newRole);
      await reload();
    } catch (e: any) {
      setError(e.message);
    }
  }

  async function handleActive(user: UserRow, isActive: boolean) {
    setError("");
    try {
      await updateUserActive(user.id, isActive);
      await reload();
    } catch (e: any) {
      setError(e.message);
    }
  }

  if (loading) return <div className="p-8">Loading...</div>;
  if (me?.role !== "admin") {
    return <div className="p-8 text-red-500">Admin access required.</div>;
  }

  return (
    <div className="min-h-screen">
      <Nav role={me.role} />
      <div className="max-w-5xl mx-auto p-6">
        <h1 className="text-2xl font-bold mb-6">Users</h1>
        {error && <p className="text-red-500 text-sm mb-3">{error}</p>}
        <div className="bg-white border rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="text-left px-4 py-2 font-medium">Email</th>
                <th className="text-left px-4 py-2 font-medium">Role</th>
                <th className="text-left px-4 py-2 font-medium">Active</th>
                <th className="text-left px-4 py-2 font-medium">Created</th>
                <th className="text-left px-4 py-2 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => {
                const isSelf = me?.id === u.id;
                const date = u.created_at ? new Date(u.created_at).toLocaleDateString() : "—";
                return (
                  <tr key={u.id} className="border-b last:border-b-0">
                    <td className="px-4 py-2">{u.email}{isSelf && <span className="text-xs text-gray-400 ml-1">(you)</span>}</td>
                    <td className="px-4 py-2">
                      <span className={`text-xs px-2 py-0.5 rounded-full ${u.role === "admin" ? "bg-indigo-100 text-indigo-800" : "bg-gray-100 text-gray-700"}`}>
                        {u.role}
                      </span>
                    </td>
                    <td className="px-4 py-2">
                      <span className={`text-xs px-2 py-0.5 rounded-full ${u.is_active ? "bg-green-100 text-green-800" : "bg-red-100 text-red-700"}`}>
                        {u.is_active ? "active" : "disabled"}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-gray-500">{date}</td>
                    <td className="px-4 py-2">
                      <div className="flex gap-2">
                        <button
                          onClick={() => handleRole(u, u.role === "admin" ? "member" : "admin")}
                          disabled={isSelf}
                          className="text-xs px-2 py-1 rounded border hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
                        >
                          {u.role === "admin" ? "Demote" : "Promote"}
                        </button>
                        <button
                          onClick={() => handleActive(u, !u.is_active)}
                          disabled={isSelf}
                          className="text-xs px-2 py-1 rounded border hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
                        >
                          {u.is_active ? "Deactivate" : "Activate"}
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
