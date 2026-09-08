import { defineConfig } from "astro/config";
import starlight from "@astrojs/starlight";

const site = process.env.PUBLIC_SITE_URL || "https://caberos-website.pages.dev";

export default defineConfig({
  site,
  trailingSlash: "always",
  integrations: [
    starlight({
      title: "CaberOS",
      description: "Documentation for the local-first operating system for personal AI agents.",
      defaultLocale: "root",
      locales: {
        root: { label: "English", lang: "en" },
        vi: { label: "Tiếng Việt", lang: "vi" },
      },
      logo: {
        src: "./src/assets/logo-mark.svg",
        alt: "CaberOS",
      },
      favicon: "/caberos-favicon.svg",
      social: [
        {
          icon: "github",
          label: "GitHub",
          href: "https://github.com/cabernect/caberos",
        },
      ],
      customCss: ["./src/styles/docs.css"],
      sidebar: [
        {
          label: "Start here",
          items: [
            { slug: "docs" },
            { slug: "docs/getting-started/installation" },
            { slug: "docs/getting-started/first-launch" },
            { slug: "docs/getting-started/provider-setup" },
            { slug: "docs/getting-started/first-agent" },
          ],
        },
        {
          label: "Core concepts",
          items: [{ autogenerate: { directory: "docs/core-concepts" } }],
        },
        {
          label: "Guides",
          items: [{ autogenerate: { directory: "docs/guides" } }],
        },
        {
          label: "Operations",
          items: [{ autogenerate: { directory: "docs/operations" } }],
        },
        {
          label: "Security",
          items: [{ autogenerate: { directory: "docs/security" } }],
        },
        {
          label: "Development",
          items: [{ autogenerate: { directory: "docs/development" } }],
        },
      ],
    }),
  ],
});
