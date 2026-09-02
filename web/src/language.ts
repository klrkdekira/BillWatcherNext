/**
 * Which language a reader sees a bill in.
 *
 * Federal legislation is published in both Malay and English, and ADR-040 carries that all the way
 * through the pipeline: a document records the listing language that named it, and the language
 * becomes a permanent component of the Expression IRI (ADR-024). So `/akn/my/bill/dr/2024/11/msa@`
 * and `.../eng@` are two Expressions of **one** Work — the same bill, not two bills, and not one
 * bill and its translation.
 *
 * That is what this module serves. A reader picks a language once; every page then shows the
 * expression in it, falls back to the other when this bill was only read in one, and says which
 * happened rather than quietly substituting. Nothing here fetches or derives — the catalogue
 * already carries the tagging, and inventing a second notion of language in the frontend is how
 * the two would come to disagree.
 */

import { titleOf, type Expression, type Work } from "./catalogue";

/** Malay first: it is the authoritative language of Malaysian federal legislation. */
export const LANGUAGES = ["ms", "en"] as const;

export type Language = (typeof LANGUAGES)[number];

/** `auto` follows the browser; the other two are the reader saying so explicitly. */
export type LanguagePreference = Language | "auto";

export const LANGUAGE_NAMES: Record<string, string> = {
  ms: "Bahasa Melayu",
  en: "English",
};

/** What a language is called in its own language, for the chooser itself. */
export const LANGUAGE_ENDONYMS: Record<LanguagePreference, string> = {
  auto: "Automatic",
  ms: "Bahasa Melayu",
  en: "English",
};

/**
 * The language to use for a reader who has not chosen one.
 *
 * Read from the browser's own ordered preferences, matching on the primary subtag so `en-GB`,
 * `en-US` and `en` are one answer. Malay is the default when nothing matches, because this is a
 * Malaysian legislative corpus and Malay is its authoritative language — not because it happens to
 * sort first.
 */
export function automaticLanguage(tags: readonly string[] = []): Language {
  for (const tag of tags) {
    const primary = tag.toLowerCase().split("-")[0];
    if (primary === "en") return "en";
    if (primary === "ms" || primary === "my") return "ms";
  }
  return "ms";
}

/** The concrete language a preference resolves to, given what the browser reports. */
export function resolve(preference: LanguagePreference, tags: readonly string[] = []): Language {
  return preference === "auto" ? automaticLanguage(tags) : preference;
}

export interface Chosen {
  expression: Expression;
  /** True when this bill has no expression in the requested language and another stood in. */
  substituted: boolean;
}

/**
 * The expression to show for one work, or `null` for a work with no expressions at all.
 *
 * Substitution is reported rather than hidden. A reader who asked for English and is looking at
 * Malay needs to know that is what happened — silently serving the other language would make the
 * corpus look as though it holds an English reading of every bill, which it does not.
 */
export function choose(work: Work, language: Language): Chosen | null {
  const wanted = work.expressions.find((expression) => expression.language === language);
  if (wanted) return { expression: wanted, substituted: false };
  const [first] = work.expressions;
  return first ? { expression: first, substituted: true } : null;
}

/** The same bill in the other language, if it was read in one. */
export function counterpart(work: Work, expression: Expression): Expression | null {
  return work.expressions.find((candidate) => candidate.language !== expression.language) ?? null;
}

/**
 * A work's title in the reader's language, falling back to whatever title it has.
 *
 * A bill read only in Malay has only a Malay title, and showing its identifier instead would be
 * worse than showing the title that exists.
 */
export function titleFor(work: Work, language: Language): string {
  return work.titles[language] ?? titleOf(work);
}

/** Every language this work was read in, in the corpus's own order. */
export function languagesOf(work: Work): Language[] {
  return LANGUAGES.filter((language) =>
    work.expressions.some((expression) => expression.language === language),
  );
}
