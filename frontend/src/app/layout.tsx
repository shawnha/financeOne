import type { Metadata } from "next";
import { IBM_Plex_Sans, IBM_Plex_Mono } from "next/font/google";
import { Suspense } from "react";
import "./globals.css";
import { cn } from "@/lib/utils";
import { Sidebar } from "@/components/sidebar";
import { Toaster } from "sonner";

const ibmPlexSans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
  variable: "--font-sans",
});

const ibmPlexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-mono",
});

export const metadata: Metadata = {
  title: "FinanceOne",
  description: "한아원 그룹 내부 회계 BPO 시스템",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko" className="dark">
      <body
        className={cn(
          "min-h-screen bg-background font-sans antialiased",
          ibmPlexSans.variable,
          ibmPlexMono.variable
        )}
      >
        <div className="flex min-h-screen">
          <Suspense fallback={null}>
            <Sidebar />
          </Suspense>
          <main className="flex-1 overflow-auto">{children}</main>
        </div>
        <Toaster
          theme="dark"
          position="top-right"
          toastOptions={{
            style: {
              background: "hsl(217 33% 17%)",
              border: "1px solid hsl(217 19% 27%)",
              color: "hsl(210 40% 98%)",
            },
          }}
        />
      </body>
    </html>
  );
}
