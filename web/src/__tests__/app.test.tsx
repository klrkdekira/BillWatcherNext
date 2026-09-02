/**
 * What the reader actually sees.
 *
 * The pipeline's own suite proves the published files are correct; these prove the page built
 * from them renders — that the routes resolve, that an FRBR identifier with no file behind it
 * reaches the right view rather than a blank page, and that the graph is redrawn as the hierarchy
 * the bill has rather than the flat set RDF stores it as.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../App";
import { CATALOGUE, JSONLD, MARKDOWN, serve } from "./fixtures";

const TREE = {
  "/index.json": CATALOGUE,
  "/akn/my/bill/dr/2024/11/msa@.md": MARKDOWN,
  "/akn/my/bill/dr/2024/11/msa@.jsonld": JSONLD,
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
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("the catalogue", () => {
  it("lists every published work once the catalogue loads", async () => {
    at("/");
    expect(await screen.findByText("RUU Keselamatan Sosial Pekerja (Pindaan) 2024")).toBeDefined();
    expect(screen.getByText("RUU Perbekalan 1990")).toBeDefined();
    // The chamber and number come from the identifier, not from a second published field.
    expect(screen.getByText("DR 11/2024")).toBeDefined();
    expect(screen.getByText("DN 37/1990")).toBeDefined();
  });

  it("labels a reading the pipeline flagged as unreliable rather than hiding it", async () => {
    at("/");
    await screen.findByText("RUU Perbekalan 1990");
    expect(screen.getAllByText("reading suspect").length).toBeGreaterThan(0);
  });

  it("shows a bill Parliament lists but the release could not publish, labelled missing", async () => {
    at("/");
    await screen.findByText("RUU Perbekalan 1990");
    expect(screen.getByText("missing")).toBeDefined();
    // The default preference is English here, so the row carries the bill's English title.
    expect(
      screen.getByText("Malaysia Deposit Insurance Corporation (Amendment) Bill 2009"),
    ).toBeDefined();
  });

  it("explains a missing bill's gap on its own work page", async () => {
    at("/akn/my/bill/dr/2009/12");
    expect(await screen.findByText(/missing from the corpus/i)).toBeDefined();
    expect(screen.getByText(/official links are dead/i)).toBeDefined();
  });

  it("says plainly when the catalogue cannot be read", async () => {
    vi.stubGlobal("fetch", serve({}));
    at("/");
    expect(await screen.findByText(/could not be read/i)).toBeDefined();
  });
});

describe("an FRBR identifier", () => {
  it("resolves a Work URI that has no file behind it", async () => {
    at("/akn/my/bill/dr/2024/11");
    expect(
      await screen.findByRole("heading", {
        name: "RUU Keselamatan Sosial Pekerja (Pindaan) 2024",
        level: 1,
      }),
    ).toBeDefined();
    expect(screen.getByText("/akn/my/bill/dr/2024/11")).toBeDefined();
  });

  it("names every published manifestation of an expression", async () => {
    at("/akn/my/bill/dr/2024/11/msa@");
    await screen.findAllByText("Markdown");
    for (const format of ["Markdown", "JSON-LD", "N-Quads"]) {
      expect(screen.getAllByText(format).length).toBeGreaterThan(0);
    }
  });

  it("shows the not-found view for an identifier this release does not publish", async () => {
    at("/akn/my/bill/dr/1999/999");
    expect(await screen.findByText(/Nothing is published at that identifier/)).toBeDefined();
  });
});

describe("an expression", () => {
  it("renders the markdown reading", async () => {
    at("/akn/my/bill/dr/2024/11/msa@");
    expect(await screen.findByText(/Suatu Akta untuk meminda/)).toBeDefined();
  });

  it("rebuilds the provision hierarchy from the flat graph, in printed order", async () => {
    const view = at("/akn/my/bill/dr/2024/11/msa@");
    await screen.findByText(/Suatu Akta untuk meminda/);

    const structure = await screen.findByRole("tab", { name: "Structure" });
    structure.click();

    await waitFor(() => expect(screen.getByText("Tajuk ringkas")).toBeDefined());
    const headings = [...view.container.querySelectorAll(".provision__heading")].map(
      (node) => node.textContent,
    );
    expect(headings).toEqual(["Tajuk ringkas", "Pindaan seksyen 2", "Permulaan kuat kuasa"]);

    // `cl_1` has a subsection; the tree must nest it rather than list it as a fourth provision.
    expect(view.container.querySelectorAll(".tree .tree").length).toBe(1);
  });
});
