import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { LANGUAGES, resolve, type Language, type LanguagePreference } from "./language";

const KEY = "billwatcher:language";

export interface LanguageState {
  /** What the reader asked for, including `auto`. */
  preference: LanguagePreference;
  /** What that resolves to for this browser — always a concrete language. */
  language: Language;
  choose: (preference: LanguagePreference) => void;
}

const Context = createContext<LanguageState | null>(null);

function stored(): LanguagePreference {
  try {
    const value = localStorage.getItem(KEY);
    if (value === "auto" || (LANGUAGES as readonly string[]).includes(value ?? "")) {
      return value as LanguagePreference;
    }
  } catch {
    // Site data blocked. The reader still gets a working chooser for this visit.
  }
  return "auto";
}

/**
 * The reader's language, remembered.
 *
 * Shaped like `useTheme` in `App`, and persisted the same way, because it is the same kind of
 * thing: a per-reader display preference that must survive a reload but has no business in a URL.
 * The *identifiers* stay language-bearing — `/akn/…/msa@` is a real Expression IRI and linking to
 * it must always yield Malay — so this chooses which expression a reader is sent to, never what a
 * given link means.
 */
export function LanguageProvider({ children }: { children: ReactNode }) {
  const [preference, setPreference] = useState<LanguagePreference>(stored);

  useEffect(() => {
    try {
      if (preference === "auto") localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, preference);
    } catch {
      // As above: a visit without storage is still a working visit.
    }
  }, [preference]);

  const choose = useCallback((next: LanguagePreference) => {
    setPreference(next);
  }, []);

  const value = useMemo<LanguageState>(() => {
    const tags = typeof navigator === "undefined" ? [] : (navigator.languages ?? []);
    const language = resolve(preference, tags);
    return { preference, language, choose };
  }, [preference, choose]);

  useEffect(() => {
    document.documentElement.lang = value.language;
  }, [value.language]);

  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useLanguage(): LanguageState {
  const state = useContext(Context);
  if (state === null) throw new Error("useLanguage must be used inside a LanguageProvider");
  return state;
}
