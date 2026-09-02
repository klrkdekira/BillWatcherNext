/**
 * One bill, two languages, and the reader choosing between them (ADR-040, ADR-024).
 *
 * Malaysian federal legislation is published in Malay and English, and the pipeline already tags
 * both as Expressions of one Work. These prove the reader half of that: that a preference is
 * honoured and remembered, that a bill read in only one language is served with the gap named
 * rather than hidden, and — the load-bearing one — that a preference never changes what an
 * Expression IRI means.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../App";
import { automaticLanguage, choose, counterpart, languagesOf, titleFor } from "../language";
import { CATALOGUE, MARKDOWN, serve } from "./fixtures";

const BILINGUAL = CATALOGUE.works[1]!;
const MALAY_ONLY = CATALOGUE.works[0]!;

const TREE = {
  "/index.json": CATALOGUE,
  "/akn/my/bill/dr/2024/11/msa@.md": MARKDOWN,
  "/akn/my/bill/dr/2026/2/msa@.md": "# RUU Pemberian Mengikut Bilangan Orang 2026\n",
  "/akn/my/bill/dr/2026/2/eng@.md": "# Capitation Grant Bill 2026\n",
};

function at(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.stubGlobal("fetch", serve(TREE));
  localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("choosing a language", () => {
  it("defaults to Malay, the authoritative language of federal legislation", () => {
    expect(automaticLanguage([])).toBe("ms");
    expect(automaticLanguage(["fr-FR", "de"])).toBe("ms");
  });

  it("follows the browser's own ordered preferences, matching on the primary subtag", () => {
    expect(automaticLanguage(["en-GB", "ms"])).toBe("en");
    expect(automaticLanguage(["ms-MY"])).toBe("ms");
    // Order decides: the reader's first understood language wins, not the first we support.
    expect(automaticLanguage(["de", "en-US", "ms"])).toBe("en");
  });

  it("serves the expression in the chosen language and reports no substitution", () => {
    const chosen = choose(BILINGUAL, "en");
    expect(chosen?.expression.uri).toBe("/akn/my/bill/dr/2026/2/eng@");
    expect(chosen?.substituted).toBe(false);
  });

  it("substitutes the other language for a bill read in only one, and says that it did", () => {
    const chosen = choose(MALAY_ONLY, "en");
    expect(chosen?.expression.language).toBe("ms");
    expect(chosen?.substituted).toBe(true);
  });

  it("names the same bill in the other language, and nothing when there is no other", () => {
    const [malay, english] = BILINGUAL.expressions;
    expect(counterpart(BILINGUAL, malay!)?.uri).toBe(english!.uri);
    expect(counterpart(BILINGUAL, english!)?.uri).toBe(malay!.uri);
    expect(counterpart(MALAY_ONLY, MALAY_ONLY.expressions[0]!)).toBeNull();
  });

  it("titles a work in the reader's language, falling back to the title it has", () => {
    expect(titleFor(BILINGUAL, "en")).toBe("Capitation Grant Bill 2026");
    expect(titleFor(BILINGUAL, "ms")).toBe("RUU Pemberian Mengikut Bilangan Orang 2026");
    // A bill read only in Malay still shows its Malay title to an English reader: a title that
    // exists beats the bare identifier.
    expect(titleFor(MALAY_ONLY, "en")).toBe(MALAY_ONLY.titles.ms);
  });

  it("reports every language a work was read in, Malay first", () => {
    expect(languagesOf(BILINGUAL)).toEqual(["ms", "en"]);
    expect(languagesOf(MALAY_ONLY)).toEqual(["ms"]);
  });
});

describe("the catalogue in the reader's language", () => {
  it("shows a bilingual bill under the title of the chosen language", async () => {
    at("/");
    await screen.findByText("Capitation Grant Bill 2026");

    fireEvent.change(screen.getByLabelText("Preferred language"), { target: { value: "ms" } });

    await waitFor(() => {
      expect(screen.getByText("RUU Pemberian Mengikut Bilangan Orang 2026")).toBeTruthy();
    });
    expect(screen.queryByText("Capitation Grant Bill 2026")).toBeNull();
  });

  it("links a bill straight to the reading in the chosen language", async () => {
    at("/");
    const english = await screen.findByText("Capitation Grant Bill 2026");
    expect(english.getAttribute("href")).toBe("/akn/my/bill/dr/2026/2/eng@");

    fireEvent.change(screen.getByLabelText("Preferred language"), { target: { value: "ms" } });

    const malay = await screen.findByText("RUU Pemberian Mengikut Bilangan Orang 2026");
    expect(malay.getAttribute("href")).toBe("/akn/my/bill/dr/2026/2/msa@");
  });

  it("finds a bill by its title in either language, whichever is on screen", async () => {
    at("/");
    await screen.findByText("Capitation Grant Bill 2026");
    fireEvent.change(screen.getByLabelText("Preferred language"), { target: { value: "ms" } });
    await screen.findByText("RUU Pemberian Mengikut Bilangan Orang 2026");

    fireEvent.change(screen.getByPlaceholderText("Title or identifier"), {
      target: { value: "Capitation" },
    });

    // Searched in English, shown in Malay: one bill, two names for it.
    await waitFor(() => {
      expect(screen.getByText("RUU Pemberian Mengikut Bilangan Orang 2026")).toBeTruthy();
    });
  });

  it("can show only the bills that were read in the chosen language", async () => {
    at("/");
    await screen.findByText("Capitation Grant Bill 2026");

    fireEvent.change(screen.getByLabelText("Language"), { target: { value: "preferred" } });

    await waitFor(() => {
      expect(screen.getByText("Capitation Grant Bill 2026")).toBeTruthy();
    });
    // The Malay-only bills drop out for an English reader; the bilingual one stays.
    expect(screen.queryByText("RUU Perbekalan 1990")).toBeNull();
  });

  it("remembers the choice across a reload", async () => {
    const first = at("/");
    await screen.findByText("Capitation Grant Bill 2026");
    fireEvent.change(screen.getByLabelText("Preferred language"), { target: { value: "ms" } });
    await screen.findByText("RUU Pemberian Mengikut Bilangan Orang 2026");
    first.unmount();

    at("/");

    await screen.findByText("RUU Pemberian Mengikut Bilangan Orang 2026");
  });
});

describe("one bill, addressed in two languages", () => {
  it("offers the same bill in the other language from a reading", async () => {
    at("/akn/my/bill/dr/2026/2/eng@");

    const link = await screen.findByText("Read this bill in Bahasa Melayu");
    expect(link.getAttribute("href")).toBe("/akn/my/bill/dr/2026/2/msa@");
    expect(link.getAttribute("hreflang")).toBe("ms");
  });

  it("says so when a bill was only ever read in one language", async () => {
    at("/akn/my/bill/dr/2024/11/msa@");

    await screen.findByText(/has not been read in English/);
  });

  it("serves what the identifier names, whatever the reader prefers", async () => {
    at("/akn/my/bill/dr/2026/2/msa@");
    // The reader's preference resolves to English in this environment, and the Malay IRI still
    // yields Malay. An identifier that meant different things to different readers would not be
    // an identifier.
    await screen.findByText("RUU Pemberian Mengikut Bilangan Orang 2026");
    await screen.findByText(/Shown in Bahasa Melayu/);
  });

  it("names the gap on a work read in only one language", async () => {
    at("/akn/my/bill/dr/2024/11");

    await screen.findByText(/Not read in English/);
  });

  it("puts the reader's language first among a work's expressions", async () => {
    at("/akn/my/bill/dr/2026/2");

    const headings = await screen.findAllByRole("heading", { level: 3 });
    expect(within(headings[0]!).getByText("Capitation Grant Bill 2026")).toBeTruthy();
  });
});
