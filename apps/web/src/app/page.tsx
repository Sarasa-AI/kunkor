"use client";

import { useEffect, useState } from "react";

interface HealthStatus {
  status: string;
}

export default function HomePage() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    fetch(`${apiUrl}/healthz`)
      .then((res) => {
        if (!res.ok) {
          throw new Error(`خطای سرور: ${res.status}`);
        }
        return res.json();
      })
      .then((data: HealthStatus) => {
        setHealth(data);
        setLoading(false);
      })
      .catch((err: Error) => {
        setError(err.message);
        setLoading(false);
      });
  }, []);

  return (
    <main
      style={{
        maxWidth: "800px",
        margin: "60px auto",
        padding: "32px",
        borderRadius: "16px",
        backgroundColor: "#ffffff",
        boxShadow: "0 4px 6px -1px rgb(0 0 0 / 0.1)",
        lineHeight: "1.8",
      }}
    >
      <header style={{ borderBottom: "1px solid #e2e8f0", paddingBottom: "16px", marginBottom: "24px" }}>
        <h1 style={{ fontSize: "24px", margin: 0, color: "#1e293b" }}>
          پلتفرم جامع یادگیری و هدایت تحصیلی
        </h1>
        <p style={{ margin: "8px 0 0", color: "#64748b" }}>
          اسکلت فنی اولیه سامانه (TASK-00)
        </p>
      </header>

      <section
        style={{
          padding: "20px",
          borderRadius: "8px",
          backgroundColor: health?.status === "ok" ? "#f0fdf4" : "#f8fafc",
          border: `1px solid ${health?.status === "ok" ? "#bbf7d0" : "#e2e8f0"}`,
        }}
      >
        <h2 style={{ fontSize: "18px", margin: "0 0 12px", color: "#334155" }}>
          وضعیت اتصال به API:
        </h2>
        {loading && <p style={{ color: "#64748b" }}>در حال بررسی اتصال به سرویس...</p>}
        {error && (
          <p style={{ color: "#dc2626", margin: 0 }}>
            عدم برقراری ارتباط با API: {error}
          </p>
        )}
        {health && (
          <p style={{ color: "#16a34a", margin: 0, fontWeight: "bold" }}>
            وضعیت سرویس: {health.status} (پاسخ معتبر دریافت شد)
          </p>
        )}
      </section>
    </main>
  );
}
