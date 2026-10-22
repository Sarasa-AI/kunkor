import React from "react";

export const metadata = {
  title: "پلتفرم جامع یادگیری و هدایت تحصیلی",
  description: "سامانه هدایت تحصیلی و یادگیری برای نظام آموزشی ایران",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="fa" dir="rtl">
      <body
        style={{
          fontFamily: "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
          margin: 0,
          padding: 0,
          backgroundColor: "#f8fafc",
          color: "#0f172a",
        }}
      >
        {children}
      </body>
    </html>
  );
}
