import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono, Sora } from "next/font/google";

import { THEME_STORAGE_KEY } from "@/lib/constants/theme";
import { AppProviders } from "@/providers/app-providers";

import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });
const sora = Sora({ variable: "--font-sora", subsets: ["latin"], weight: ["500", "600", "700"] });

export const metadata: Metadata = {
  title: { default: "JobOrbit", template: "%s · JobOrbit" },
  description: "Your personal AI job search, application and tracking workspace.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#0d0f1a" },
    { media: "(prefers-color-scheme: light)", color: "#fafaff" },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`dark ${geistSans.variable} ${geistMono.variable} ${sora.variable}`}
      suppressHydrationWarning
    >
      <head>
        {/* Applies the saved theme before the first paint, so a light-theme user never
            sees a dark flash. Rendered by this Server Component, so it runs on full loads. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `try{var t=localStorage.getItem(${JSON.stringify(THEME_STORAGE_KEY)});if(t==="light"){document.documentElement.classList.remove("dark");document.documentElement.style.colorScheme="light"}}catch(e){}`,
          }}
        />
      </head>
      <body>
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  );
}
