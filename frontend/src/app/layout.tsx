import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Sheska",
  description: "LLM Wiki for Team",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body className="bg-gray-50 text-gray-900">{children}</body>
    </html>
  );
}
