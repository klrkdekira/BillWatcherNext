/**
 * The JSON-LD reader, tested directly.
 *
 * `graph.ts` was only ever exercised through one app test on one hand-written fixture, and the
 * shapes it got wrong were all shapes that fixture did not contain: a roman-numbered Part run, a
 * document compacted without `@graph`, a reference left as a node object. Every case here is one
 * the published corpus or JSON-LD compaction can actually produce, checked against the reader
 * rather than against a rendered page.
 */
import { describe, expect, it } from "vitest";
import { inPrintedOrder, readGraph, type JsonLdDocument, type Provision } from "../graph";

const BASE = "https://bills.engineers.my/akn/my/bill/dr/2024/11/msa@";

/** A document node plus whatever provisions a test needs, in the published compact shape. */
function document(nodes: Record<string, unknown>[], parts: unknown): JsonLdDocument {
  return {
    "@context": { akn: "http://docs.oasis-open.org/legaldocml/ns/akn/3.0#" },
    "@graph": [
      {
        "@id": BASE,
        "@type": "akn:bill",
        "eli:is_realized_by": { "@id": "https://bills.engineers.my/akn/my/bill/dr/2024/11" },
        "eli:language": "ms",
        hasPart: parts,
      },
      ...nodes,
    ],
  } as unknown as JsonLdDocument;
}

function provision(eid: string, type: string, number: string, extra: Record<string, unknown> = {}) {
  return { "@id": `${BASE}/~${eid}`, "@type": `akn:${type}`, "eli:number": number, ...extra };
}

const numbers = (provisions: Provision[]) => provisions.map((item) => item.number);

describe("readGraph", () => {
  it("rebuilds the hierarchy from the flat graph", () => {
    const graph = readGraph(
      document(
        [
          provision("cl_1", "clause", "1", { hasPart: [`${BASE}/~cl_1__subsec_1`] }),
          provision("cl_1__subsec_1", "subsection", "1"),
        ],
        [`${BASE}/~cl_1`],
      ),
    );
    expect(graph.root?.["@id"]).toBe(BASE);
    expect(graph.provisions).toHaveLength(1);
    expect(graph.provisions[0]?.type).toBe("clause");
    expect(graph.provisions[0]?.children.map((child) => child.type)).toEqual(["subsection"]);
    expect(graph.size).toBe(3);
  });

  it("reads a document that compaction left without an @graph wrapper", () => {
    // A graph with one subject compacts to a bare node. Reading `@graph` alone rendered such a
    // document as a bill with no provisions at all.
    const graph = readGraph({
      "@context": {},
      "@id": BASE,
      "@type": "akn:bill",
      "eli:is_realized_by": { "@id": "https://bills.engineers.my/akn/my/bill/dr/2024/11" },
      "eli:language": "ms",
    } as unknown as JsonLdDocument);
    expect(graph.root?.["@id"]).toBe(BASE);
    expect(graph.size).toBe(1);
    expect(graph.provisions).toEqual([]);
  });

  it("follows a reference whether it is a bare IRI or a node object", () => {
    // `hasPart` compacts to a string only because the published context types it `"@type": "@id"`.
    // The same graph under a context without that term definition carries `{"@id": ...}`.
    const graph = readGraph(
      document([provision("cl_1", "clause", "1")], [{ "@id": `${BASE}/~cl_1` }]),
    );
    expect(numbers(graph.provisions)).toEqual(["1"]);
  });

  it("accepts a single child compacted to a scalar", () => {
    const graph = readGraph(document([provision("cl_1", "clause", "1")], `${BASE}/~cl_1`));
    expect(numbers(graph.provisions)).toEqual(["1"]);
  });

  it("keeps a heading that compaction emitted as a list", () => {
    const graph = readGraph(
      document(
        [
          provision("cl_1", "clause", "1", {
            "schema:name": [
              { "@language": "ms", "@value": "Tajuk ringkas" },
              { "@language": "en", "@value": "Short title" },
            ],
          }),
        ],
        [`${BASE}/~cl_1`],
      ),
    );
    expect(graph.provisions[0]?.heading).toBe("Tajuk ringkas");
  });

  it("survives a dangling reference and a cycle rather than failing the page", () => {
    const graph = readGraph(
      document(
        [provision("cl_1", "clause", "1", { hasPart: [`${BASE}/~cl_1`, `${BASE}/~cl_999`] })],
        [`${BASE}/~cl_1`],
      ),
    );
    expect(numbers(graph.provisions)).toEqual(["1"]);
    expect(graph.provisions[0]?.children).toEqual([]);
  });
});

/** A sibling list of one provision type, as `ProvisionTree` hands one to `inPrintedOrder`. */
const group = (type: string, values: string[]): Provision[] =>
  values.map((number) => ({
    id: `${type}_${number}`,
    type,
    number,
    heading: null,
    language: "ms",
    children: [],
  }));

describe("inPrintedOrder", () => {
  it("orders decimal numbers numerically, with inserted provisions after their base", () => {
    expect(numbers(inPrintedOrder(group("clause", ["10", "1", "5A", "5", "2"])))).toEqual([
      "1",
      "2",
      "5",
      "5A",
      "10",
    ]);
  });

  it("orders a roman-numbered Part run by value, not as text", () => {
    // The regression: eight published documents listed their Parts I, II, III, IV, IX, V, ...
    // because a non-decimal number fell through to `localeCompare`.
    const parts = group("part", [
      "I",
      "IX",
      "V",
      "II",
      "X",
      "IV",
      "XI",
      "III",
      "VIII",
      "VI",
      "VII",
    ]);
    expect(numbers(inPrintedOrder(parts))).toEqual([
      "I",
      "II",
      "III",
      "IV",
      "V",
      "VI",
      "VII",
      "VIII",
      "IX",
      "X",
      "XI",
    ]);
  });

  it("orders lower-case roman subparagraphs by value", () => {
    expect(numbers(inPrintedOrder(group("subparagraph", ["ix", "i", "iv", "v", "ii"])))).toEqual([
      "i",
      "ii",
      "iv",
      "v",
      "ix",
    ]);
  });

  it("leaves a lettered subparagraph run alphabetical", () => {
    // Malaysian drafting nests `subparagraph` at a roman depth AND at a plain lettered one. `C` and
    // `D` are valid roman numerals; `A` and `B` are not, so the run is read as letters — the same
    // tie-break the fidelity gate makes for the identical ambiguity.
    expect(numbers(inPrintedOrder(group("subparagraph", ["D", "A", "C", "B"])))).toEqual([
      "A",
      "B",
      "C",
      "D",
    ]);
  });

  it("leaves a lettered paragraph run alphabetical even where the letters read as roman", () => {
    expect(numbers(inPrintedOrder(group("paragraph", ["i", "c", "d"])))).toEqual(["c", "d", "i"]);
  });
});
