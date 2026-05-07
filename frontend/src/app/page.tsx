"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function Home() {
  const router = useRouter();
  useEffect(() => {
    const token = localStorage.getItem("sheska_token");
    router.replace(token ? "/wiki" : "/login");
  }, [router]);
  return null;
}
