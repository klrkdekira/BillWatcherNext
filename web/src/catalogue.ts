/**
 * The published catalogue, exactly as `index.json` carries it.
 *
 * These types are a mirror of what `billwatcher.publish.dataset` writes, and deliberately nothing
 * more: the frontend derives what it needs (a year, a chamber, a file's format) from the
 * identifiers themselves rather than asking the pipeline to publish a second, redundant shape that
 * could disagree with the first.
 */

export interface Reading {
  extractor: string;
  suspect: boolean;
  heading_ratio?: number;
  lone_letter_rate?: number;
}

export interface Expression {
  /** The FRBR Expression IRI path, e.g. `/akn/my/bill/dr/2024/11/msa@`. */
  uri: string;
  language: string;
  title: string | null;
  /** Root-relative paths of every published manifestation of this expression. */
  files: string[];
  reading?: Reading;
}

export interface Work {
  /** The FRBR Work IRI path, e.g. `/akn/my/bill/dr/2024/11`. */
  uri: string;
  titles: Record<string, string>;
  expressions: Expression[];
  /** Present when Parliament lists this bill but the release could publish nothing of it. */
  missing?: {
    /** Where the gap is: the listing named no files, the download never succeeded, or the
        reading of what was downloaded did not meet the publication bar. */
    reason: "listing" | "download" | "reading" | string;
    documents_listed?: number;
  };
}

/** What each missing reason means, in words a reader can act on. */
export const MISSING_REASONS: Record<string, string> = {
  listing: "Parliament's listing names this bill but attaches no document files to it.",
  download:
    "Parliament's listing links document files for this bill, but none could be downloaded — " +
    "the official links are dead.",
  reading:
    "The bill's documents are stored, but no reading of them met the publication bar — " +
    "usually a scanned copy with no text layer.",
};

export interface Catalogue {
  catalogue_version: number;
  publication_mode: "metadata" | "full";
  representations: string[];
  works: Work[];
}

export interface WorkIdentity {
  chamber: "dr" | "dn" | string;
  year: number;
  number: string;
}

const WORK_URI = /^\/akn\/my\/bill\/([a-z]+)\/(\d{4})\/([^/]+)$/;

/** Read a work's chamber, year and number back out of its own identifier. */
export function identify(work: Work): WorkIdentity | null {
  const match = WORK_URI.exec(work.uri);
  if (!match) return null;
  const [, chamber, year, number] = match;
  if (!chamber || !year || !number) return null;
  return { chamber, year: Number(year), number };
}

export const CHAMBER_NAMES: Record<string, string> = {
  dr: "Dewan Rakyat",
  dn: "Dewan Negara",
};

export const FORMAT_NAMES: Record<string, string> = {
  md: "Markdown",
  jsonld: "JSON-LD",
  nq: "N-Quads",
  xml: "Akoma Ntoso XML",
};

/** The manifestation extension of a published file, e.g. `jsonld` for `…/msa@.jsonld`. */
export function formatOf(file: string): string {
  const dot = file.lastIndexOf(".");
  return dot === -1 ? file : file.slice(dot + 1);
}

export function titleOf(work: Work): string {
  const titles = Object.values(work.titles);
  return titles[0] ?? work.uri;
}

/**
 * Fetch a file from the published tree.
 *
 * Everything the app reads is a static file beside it, which is the whole architecture: there is
 * no API, and a reader who prefers `curl` gets the identical bytes at the identical URL.
 */
/**
 * A published file's URL, for links and fetches alike. The dataset addresses everything by
 * root-relative FRBR paths; on a path-hosted Pages site (`cheeleong.dev/data-parlimen/`) the
 * whole tree — app and dataset together — lives under Vite's `base`, so that base is the one
 * thing standing between an identifier and the bytes it names.
 */
export function publishedUrl(path: string): string {
  return `${import.meta.env.BASE_URL}${path.replace(/^\//, "")}`;
}

export async function fetchPublished(path: string): Promise<Response> {
  const response = await fetch(publishedUrl(path));
  if (!response.ok) throw new Error(`${response.status} ${response.statusText} for /${path}`);
  return response;
}

export async function loadCatalogue(): Promise<Catalogue> {
  return (await fetchPublished("index.json")).json() as Promise<Catalogue>;
}
