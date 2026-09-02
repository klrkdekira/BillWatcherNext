import type { Catalogue } from "../catalogue";

/**
 * A catalogue with the shapes the corpus actually contains: a bill read in **both** published
 * languages (ADR-040), one read only in Malay, and one whose reading is flagged unreliable — plus
 * the manifestation mix, since an expression may have a reading with or without a graph.
 *
 * The bilingual work is the important one. Two Expressions of one Work is the case the whole
 * language model turns on, and a fixture with only single-language works would let every
 * substitution and fallback path pass untested.
 *
 * Hand-written rather than trimmed from the real `index.json` so that a change in the corpus
 * cannot quietly change what these tests assert.
 */
export const CATALOGUE: Catalogue = {
  catalogue_version: 1,
  publication_mode: "full",
  representations: ["md", "jsonld", "nq"],
  works: [
    {
      uri: "/akn/my/bill/dr/2024/11",
      titles: { ms: "RUU Keselamatan Sosial Pekerja (Pindaan) 2024" },
      expressions: [
        {
          uri: "/akn/my/bill/dr/2024/11/msa@",
          language: "ms",
          title: "RUU Keselamatan Sosial Pekerja (Pindaan) 2024",
          files: [
            "akn/my/bill/dr/2024/11/msa@.md",
            "akn/my/bill/dr/2024/11/msa@.jsonld",
            "akn/my/bill/dr/2024/11/msa@.nq",
          ],
          reading: { extractor: "pdfminer-layout", suspect: false },
        },
      ],
    },
    {
      uri: "/akn/my/bill/dr/2026/2",
      titles: {
        ms: "RUU Pemberian Mengikut Bilangan Orang 2026",
        en: "Capitation Grant Bill 2026",
      },
      expressions: [
        {
          uri: "/akn/my/bill/dr/2026/2/msa@",
          language: "ms",
          title: "RUU Pemberian Mengikut Bilangan Orang 2026",
          files: ["akn/my/bill/dr/2026/2/msa@.md"],
          reading: { extractor: "pdfminer-layout", suspect: false },
        },
        {
          uri: "/akn/my/bill/dr/2026/2/eng@",
          language: "en",
          title: "Capitation Grant Bill 2026",
          files: ["akn/my/bill/dr/2026/2/eng@.md"],
          reading: { extractor: "pdfminer-layout", suspect: false },
        },
      ],
    },
    {
      uri: "/akn/my/bill/dn/1990/37",
      titles: { ms: "RUU Perbekalan 1990" },
      expressions: [
        {
          uri: "/akn/my/bill/dn/1990/37/msa@",
          language: "ms",
          title: "RUU Perbekalan 1990",
          files: ["akn/my/bill/dn/1990/37/msa@.md"],
          reading: { extractor: "pdfminer-layout", suspect: true, heading_ratio: 0.81 },
        },
      ],
    },
    {
      // A bill Parliament lists but the release could publish nothing of: no expressions, and a
      // reason. It must appear — labelled — rather than silently not existing.
      uri: "/akn/my/bill/dr/2009/12",
      titles: {
        ms: "RUU Perbadanan Insurans Deposit Malaysia (Pindaan) 2009",
        en: "Malaysia Deposit Insurance Corporation (Amendment) Bill 2009",
      },
      expressions: [],
      missing: { reason: "download", documents_listed: 2 },
    },
  ],
};

export const MARKDOWN = `<!-- page 1 -->

# RUU Keselamatan Sosial Pekerja (Pindaan) 2024

Suatu Akta untuk meminda Akta Keselamatan Sosial Pekerja 1969.
`;

export const JSONLD = {
  "@context": { akn: "http://docs.oasis-open.org/legaldocml/ns/akn/3.0#" },
  "@graph": [
    {
      "@id": "https://bills.engineers.my/akn/my/bill/dr/2024/11/msa@",
      "@type": "akn:bill",
      "eli:is_realized_by": { "@id": "https://bills.engineers.my/akn/my/bill/dr/2024/11" },
      "eli:language": "ms",
      // Deliberately out of printed order: the reader must restore 1, 2, 10 rather than 1, 10, 2.
      hasPart: [
        "https://bills.engineers.my/akn/my/bill/dr/2024/11/msa@/~cl_10",
        "https://bills.engineers.my/akn/my/bill/dr/2024/11/msa@/~cl_1",
        "https://bills.engineers.my/akn/my/bill/dr/2024/11/msa@/~cl_2",
      ],
    },
    {
      "@id": "https://bills.engineers.my/akn/my/bill/dr/2024/11/msa@/~cl_1",
      "@type": "akn:clause",
      "eli:number": "1",
      "schema:name": { "@language": "ms", "@value": "Tajuk ringkas" },
      hasPart: ["https://bills.engineers.my/akn/my/bill/dr/2024/11/msa@/~cl_1__subsec_1"],
    },
    {
      "@id": "https://bills.engineers.my/akn/my/bill/dr/2024/11/msa@/~cl_1__subsec_1",
      "@type": "akn:subsection",
      "eli:number": "1",
    },
    {
      "@id": "https://bills.engineers.my/akn/my/bill/dr/2024/11/msa@/~cl_2",
      "@type": "akn:clause",
      "eli:number": "2",
      "schema:name": { "@language": "ms", "@value": "Pindaan seksyen 2" },
    },
    {
      "@id": "https://bills.engineers.my/akn/my/bill/dr/2024/11/msa@/~cl_10",
      "@type": "akn:clause",
      "eli:number": "10",
      "schema:name": { "@language": "ms", "@value": "Permulaan kuat kuasa" },
    },
  ],
};

/**
 * Stand in for the published tree. The app fetches static files and nothing else, so a map from
 * path to body is a complete substitute for the server.
 */
export function serve(files: Record<string, unknown>): typeof fetch {
  return ((input: RequestInfo | URL) => {
    const path = String(input);
    const body = files[path];
    if (body === undefined) {
      return Promise.resolve(new Response("not found", { status: 404, statusText: "Not Found" }));
    }
    return Promise.resolve(
      new Response(typeof body === "string" ? body : JSON.stringify(body), { status: 200 }),
    );
  }) as typeof fetch;
}
