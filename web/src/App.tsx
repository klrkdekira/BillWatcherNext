import { useCallback, useEffect, useState } from "react";
import { Link, Route, Routes } from "react-router";

import { publishedUrl } from "./catalogue";
import { CatalogueProvider } from "./CatalogueContext";
import { LanguageProvider, useLanguage } from "./LanguageContext";
import { LANGUAGE_ENDONYMS, type LanguagePreference } from "./language";
import { CataloguePage } from "./routes/CataloguePage";
import { ExpressionPage } from "./routes/ExpressionPage";
import { NotFoundPage } from "./routes/NotFoundPage";
import { WorkPage } from "./routes/WorkPage";

const THEME_KEY = "billwatcher:theme";

/*
 * What a mobile browser paints its own chrome with, for a reader who has overridden their system.
 *
 * `index.html` declares one `theme-color` per system preference, which is right until someone asks
 * this site for dark on a light phone — then the address bar stays the colour of the theme they
 * just left, and the page appears to end in a band of the wrong paper. A meta with no media query
 * always matches, and the browser takes the first match in document order, so prepending one wins
 * over the declared pair; removing it hands control back.
 */
const THEME_COLORS: Record<string, string> = { light: "#f1ebdf", dark: "#211b15" };
const OVERRIDE_ID = "theme-color-override";

function paintBrowserChrome(theme: string) {
  let meta = document.getElementById(OVERRIDE_ID) as HTMLMetaElement | null;
  if (theme === "system") {
    meta?.remove();
    return;
  }
  if (!meta) {
    meta = document.createElement("meta");
    meta.id = OVERRIDE_ID;
    meta.name = "theme-color";
    document.head.prepend(meta);
  }
  meta.content = THEME_COLORS[theme] ?? THEME_COLORS.light!;
}

function useTheme(): [string, () => void] {
  const [theme, setTheme] = useState<string>(() => {
    try {
      return localStorage.getItem(THEME_KEY) ?? "system";
    } catch {
      return "system";
    }
  });

  useEffect(() => {
    if (theme === "system") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = theme;
    paintBrowserChrome(theme);
    try {
      if (theme === "system") localStorage.removeItem(THEME_KEY);
      else localStorage.setItem(THEME_KEY, theme);
    } catch {
      // A browser with site data blocked still gets a working toggle for this visit.
    }
  }, [theme]);

  const cycle = useCallback(() => {
    setTheme((current) =>
      current === "system" ? "light" : current === "light" ? "dark" : "system",
    );
  }, []);

  return [theme, cycle];
}

/**
 * Which language the reader is served, chosen once and applied everywhere.
 *
 * A control rather than a URL parameter: the language-bearing identifiers are the Expression IRIs
 * themselves, and `/akn/my/bill/dr/2024/11/msa@` must mean Malay to everyone who follows it. This
 * only decides which of a bill's expressions a reader is *sent to* by default.
 */
function LanguageChooser() {
  const { preference, language, choose } = useLanguage();

  return (
    <label className="chooser">
      <span className="chooser__label">Preferred language</span>
      <select
        aria-label="Preferred language"
        value={preference}
        onChange={(event) => {
          choose(event.target.value as LanguagePreference);
        }}
      >
        {(["auto", "ms", "en"] as const).map((option) => (
          <option key={option} value={option}>
            {option === "auto"
              ? `${LANGUAGE_ENDONYMS.auto} (${LANGUAGE_ENDONYMS[language]})`
              : LANGUAGE_ENDONYMS[option]}
          </option>
        ))}
      </select>
    </label>
  );
}

export function App() {
  const [theme, cycleTheme] = useTheme();

  return (
    <LanguageProvider>
      <CatalogueProvider>
        <header className="masthead">
          <div className="masthead__inner">
            <p className="masthead__title">
              <Link to="/">Malaysian Parliament Bills</Link>
            </p>
            <nav className="masthead__nav">
              <a href={publishedUrl("index.json")}>index.json</a>
              <a href={publishedUrl("definitions/jsonld-context.jsonld")}>JSON-LD context</a>
              <a href={publishedUrl("checksums.sha256")}>checksums</a>
              <LanguageChooser />
              <button className="theme-toggle" type="button" onClick={cycleTheme}>
                theme: {theme}
              </button>
            </nav>
          </div>
        </header>

        <main className="shell">
          <Routes>
            <Route index element={<CataloguePage />} />
            <Route path="/akn/my/bill/:chamber/:year/:number" element={<WorkPage />} />
            <Route
              path="/akn/my/bill/:chamber/:year/:number/:expression"
              element={<ExpressionPage />}
            />
            <Route path="*" element={<NotFoundPage />} />
          </Routes>

          <footer className="footer">
            <p>
              Every page here is built from static files in this same tree. The identifiers are FRBR
              paths under <code>/akn/my/bill/…</code>, and each one dereferences to the bytes it
              names — no API sits between them.
            </p>
          </footer>
        </main>
      </CatalogueProvider>
    </LanguageProvider>
  );
}
