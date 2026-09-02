/**
 * Reading the published JSON-LD back into the provision tree it was serialised from.
 *
 * The graph is flat — every provision is a sibling node related by `hasPart`/`isPartOf` — because
 * that is what RDF wants. A reader wants the hierarchy the bill actually has, so this rebuilds it.
 *
 * Nodes are keyed by the *path* of their `@id`, never the whole IRI. The IRIs are absolute and
 * carry whichever base the corpus was built with; keying on the path means a dataset built against
 * a development base still renders correctly when served from the published domain, rather than
 * silently collapsing into a tree of orphans.
 */

export interface JsonLdNode {
  "@id": string;
  "@type"?: string | string[];
  "eli:number"?: string;
  "eli:language"?: string;
  "eli:is_realized_by"?: { "@id": string };
  "schema:name"?: { "@language": string; "@value": string } | string;
  hasPart?: string[] | string;
  isPartOf?: string;
  [key: string]: unknown;
}

export interface JsonLdDocument {
  "@context": Record<string, unknown>;
  /**
   * Optional, and that is not defensive typing. JSON-LD compaction only wraps nodes in `@graph`
   * when there is more than one subject: a document whose every provision was withheld compacts to
   * a bare node object with `@id` at the top level and no `@graph` key, which is why the publisher
   * (`graph.semantic.render_jsonld`) tests for the key before sorting it.
   */
  "@graph"?: JsonLdNode[];
  "@id"?: string;
}

export interface Provision {
  id: string;
  /** `clause`, `subsection`, `schedule`… — the `akn:` prefix stripped. */
  type: string;
  number: string | null;
  heading: string | null;
  language: string | null;
  children: Provision[];
}

function pathOf(iri: string): string {
  const marker = iri.indexOf("/akn/");
  return marker === -1 ? iri : iri.slice(marker);
}

/**
 * The IRI behind a reference, whether it was compacted to a bare string or left as a node object.
 *
 * Both are the same JSON-LD. `hasPart` and `isPartOf` compact to strings only because the published
 * context types them `"@type": "@id"`; the same graph served with a context that does not — an older
 * file, or `definitions/jsonld-context.jsonld` drifting from the renderer — carries `{"@id": ...}`
 * instead. Reading only the string form turned that into `iri.indexOf is not a function` on a page
 * that had nothing wrong with it.
 */
function idOf(value: unknown): string | null {
  if (typeof value === "string") return value;
  if (value !== null && typeof value === "object") {
    const nested = (value as { "@id"?: unknown })["@id"];
    if (typeof nested === "string") return nested;
  }
  return null;
}

function typeOf(node: JsonLdNode): string {
  const raw = node["@type"];
  const first = Array.isArray(raw) ? raw[0] : raw;
  return (first ?? "unknown").replace(/^akn:/, "");
}

function headingOf(node: JsonLdNode): string | null {
  // An array when a node carries more than one `schema:name` — rdflib compacts a single value to a
  // scalar and anything else to a list. Taking the first is a display choice, not a claim about
  // which is authoritative; dropping the heading entirely (what reading `["@value"]` off an array
  // silently did) is the one answer that is certainly wrong.
  const raw = node["schema:name"];
  const name = Array.isArray(raw) ? raw[0] : raw;
  if (typeof name === "string") return name;
  return name?.["@value"] ?? null;
}

function partsOf(node: JsonLdNode): string[] {
  const parts = node.hasPart;
  if (!parts) return [];
  const listed: unknown[] = Array.isArray(parts) ? parts : [parts];
  return listed.map(idOf).filter((part): part is string => part !== null);
}

/**
 * The nodes of a document, whether or not compaction wrapped them in `@graph`.
 *
 * See `JsonLdDocument["@graph"]`: a one-subject graph has no wrapper, and reading `@graph` alone
 * rendered such a document as a bill with no provisions rather than as the one node it has.
 */
function nodesOf(document: JsonLdDocument): JsonLdNode[] {
  const graph = document["@graph"];
  if (Array.isArray(graph)) return graph;
  return typeof document["@id"] === "string" ? [document as unknown as JsonLdNode] : [];
}

export interface ExpressionGraph {
  /** The expression node itself: the bill or act the provisions belong to. */
  root: JsonLdNode | null;
  provisions: Provision[];
  /** Every node in the graph, provisions and expression alike. */
  size: number;
}

export function readGraph(document: JsonLdDocument): ExpressionGraph {
  const graph = nodesOf(document);
  const nodes = new Map<string, JsonLdNode>();
  for (const node of graph) nodes.set(pathOf(node["@id"]), node);

  // The expression is the node that realises a work; everything else hangs off it by `hasPart`.
  const root = graph.find((node) => node["eli:is_realized_by"] !== undefined) ?? null;

  const seen = new Set<string>();
  const build = (id: string): Provision | null => {
    const key = pathOf(id);
    const node = nodes.get(key);
    // A cycle would hang the render, and a dangling `hasPart` is a graph that lost a node in
    // transit — both are worth surviving rather than crashing the page over.
    if (!node || seen.has(key)) return null;
    seen.add(key);
    const language = root?.["eli:language"] ?? null;
    return {
      id: key,
      type: typeOf(node),
      number: node["eli:number"] ?? null,
      heading: headingOf(node),
      language: typeof language === "string" ? language : null,
      children: partsOf(node)
        .map(build)
        .filter((child): child is Provision => child !== null),
    };
  };

  const provisions = root
    ? partsOf(root)
        .map(build)
        .filter((child): child is Provision => child !== null)
    : [];

  return { root, provisions, size: nodes.size };
}

/**
 * The provision types Malaysian drafting numbers in roman: `BAHAGIAN II`, `Bab 1`, `(ii)`.
 *
 * Keyed on the type rather than on the token, for the reason the gate that judges these same
 * numbers records (`graph.fidelity._ROMAN_NUMBERED`): `I` is simultaneously a valid roman numeral
 * and a valid paragraph letter, so only the type says which a given run is.
 */
const ROMAN_NUMBERED = new Set(["part", "chapter", "subparagraph"]);

const ROMAN_DIGITS: Record<string, number> = { i: 1, v: 5, x: 10, l: 50, c: 100, d: 500, m: 1000 };

/** The value of a roman numeral, or null when the token is not one. */
function romanValue(token: string): number | null {
  const digits: number[] = [];
  for (const character of token.toLowerCase()) {
    const digit = ROMAN_DIGITS[character];
    if (digit === undefined) return null;
    digits.push(digit);
  }
  if (digits.length === 0) return null;
  // Subtractive: a digit smaller than the one after it is taken away rather than added, so `ix` is
  // 9 and not 11. Non-canonical spellings (`iiii`) still resolve, because a printed page is the
  // authority here and rejecting one would silently drop the provision out of order.
  let total = 0;
  for (let index = 0; index < digits.length; index += 1) {
    const digit = digits[index]!;
    total += digit < (digits[index + 1] ?? 0) ? -digit : digit;
  }
  return total;
}

/**
 * Whether a sibling list is a roman-numbered run, and so must be ordered by value.
 *
 * Both halves are needed. The type alone is not enough: Malaysian drafting nests `subparagraph` at
 * a roman-numbered depth (`i`, `ii`) *and* at a plain lettered one (`A`, `B`, `C`, `D`), and the
 * lettered run must stay lettered — `A` is not a roman numeral, so a real `A, B, C, D` fails this
 * test and keeps the alphabetic ordering below, which is the same tie-break `fidelity._compare`
 * makes for the identical ambiguity.
 */
function isRomanRun(provisions: Provision[]): boolean {
  return (
    provisions.length > 1 &&
    provisions.every(
      (provision) =>
        ROMAN_NUMBERED.has(provision.type) && romanValue(provision.number ?? "") !== null,
    )
  );
}

/**
 * Sort provisions the way the printed document numbers them: 1, 2, 5A, 10 — not 1, 10, 2, 5A.
 *
 * The graph publishes `hasPart` as a set, and JSON serialises it in the order rdflib emitted,
 * which is lexical. A reader comparing the page to the paper needs the paper's order.
 *
 * A number that is not decimal used to fall through to `localeCompare`, which reads a roman numeral
 * as a string: eight published documents listed their Parts `I, II, III, IV, IX, V, VI, VII, VIII,
 * X, XI`, and a bill's Parts are the first thing on its structure tab. Roman runs are therefore
 * ordered by value, and everything else keeps the decimal-then-suffix key that already handled the
 * inserted-provision case (`5`, `5A`, `6`).
 */
function printedOrderKey(provision: Provision): [number, string] {
  const match = /^(\d+)(.*)$/.exec(provision.number ?? "");
  if (!match) return [Number.MAX_SAFE_INTEGER, provision.number ?? ""];
  return [Number(match[1]), match[2] ?? ""];
}

export function inPrintedOrder(provisions: Provision[]): Provision[] {
  if (isRomanRun(provisions)) {
    return provisions.toSorted(
      (left, right) => romanValue(left.number ?? "")! - romanValue(right.number ?? "")!,
    );
  }
  return provisions.toSorted((left, right) => {
    const [leftNumber, leftSuffix] = printedOrderKey(left);
    const [rightNumber, rightSuffix] = printedOrderKey(right);
    return leftNumber - rightNumber || leftSuffix.localeCompare(rightSuffix);
  });
}
