import { useEffect, useState } from "react";
import Markdown from "react-markdown";
import { Link, useParams } from "react-router";
import remarkGfm from "remark-gfm";

import {
  FORMAT_NAMES,
  fetchPublished,
  formatOf,
  publishedUrl,
  type Expression,
  type Work,
} from "../catalogue";
import { useCatalogue } from "../CatalogueContext";
import { useLanguage } from "../LanguageContext";
import { counterpart, LANGUAGE_NAMES } from "../language";
import { inPrintedOrder, readGraph, type JsonLdDocument, type Provision } from "../graph";
import { NotFoundPage } from "./NotFoundPage";

type Tab = "reading" | "structure" | "graph";

export function ExpressionPage() {
  const { chamber, year, number, expression: segment } = useParams();
  const state = useCatalogue();
  const uri = `/akn/my/bill/${chamber}/${year}/${number}/${segment}`;

  if (state.status === "loading") return <p className="muted">Loading…</p>;
  if (state.status === "failed") return <p className="muted">The catalogue could not be read.</p>;

  let found: { work: Work; expression: Expression } | null = null;
  for (const work of state.catalogue.works) {
    const expression = work.expressions.find((candidate) => candidate.uri === uri);
    if (expression) {
      found = { work, expression };
      break;
    }
  }
  if (!found) return <NotFoundPage />;

  return <ExpressionView work={found.work} expression={found.expression} />;
}

function ExpressionView({ work, expression }: { work: Work; expression: Expression }) {
  const { language, choose } = useLanguage();
  const other = counterpart(work, expression);
  const files = new Map(expression.files.map((file) => [formatOf(file), file]));
  const available: Tab[] = [];
  if (files.has("md")) available.push("reading");
  if (files.has("jsonld")) available.push("structure", "graph");
  const [tab, setTab] = useState<Tab>(available[0] ?? "reading");

  return (
    <>
      <p className="crumbs">
        <Link to="/">All bills</Link> › <Link to={work.uri}>{work.uri}</Link>
      </p>
      <h1 className="display">{expression.title ?? expression.uri}</h1>
      <p className="lede">
        <code>{expression.uri}</code> ·{" "}
        <span className="pill pill--accent">
          {LANGUAGE_NAMES[expression.language] ?? expression.language}
        </span>
      </p>

      {/* The same bill, addressed in the other language. Following this switches the reader's
          preference too: someone who reaches for the English of one bill almost always wants the
          English of the next one, and making them say so twice is the annoyance this removes. */}
      {other ? (
        <p className="lede">
          <Link
            to={other.uri}
            hrefLang={other.language}
            onClick={() => {
              choose(other.language as "ms" | "en");
            }}
          >
            Read this bill in {LANGUAGE_NAMES[other.language] ?? other.language}
          </Link>
        </p>
      ) : (
        <p className="muted">
          This bill has not been read in{" "}
          {LANGUAGE_NAMES[expression.language === "ms" ? "en" : "ms"]}. Parliament publishes federal
          legislation in both languages; only one reading of this one is in the corpus.
        </p>
      )}

      {expression.language === language ? null : (
        <div className="notice notice--warn">
          <strong>Shown in {LANGUAGE_NAMES[expression.language] ?? expression.language}.</strong>{" "}
          You have asked for {LANGUAGE_NAMES[language]}, and this expression is not in it. The
          identifier decides the language, so this page always serves what{" "}
          <code>{expression.uri}</code> names.
        </div>
      )}

      {expression.reading?.suspect ? (
        <div className="notice notice--warn">
          <strong>This reading is flagged as unreliable.</strong> Its measured shape is far outside
          the corpus — mostly headings, or letter-spaced body text — which usually means the PDF did
          not read cleanly. It is published labelled rather than withheld, so you can see it and
          judge it.
        </div>
      ) : null}

      <ul className="resources">
        {expression.files.map((file) => (
          <li className="resource" key={file}>
            <a className="resource__format" href={publishedUrl(file)}>
              {FORMAT_NAMES[formatOf(file)] ?? formatOf(file)}
            </a>
            <span className="resource__path">/{file}</span>
          </li>
        ))}
      </ul>

      {available.length === 0 ? (
        <p className="muted">No representation of this expression is published in this release.</p>
      ) : (
        <>
          <div className="tabs" role="tablist">
            {available.map((name) => (
              <button
                key={name}
                type="button"
                role="tab"
                className="tab"
                aria-selected={tab === name}
                onClick={() => setTab(name)}
              >
                {name === "reading" ? "Reading" : name === "structure" ? "Structure" : "JSON-LD"}
              </button>
            ))}
          </div>
          {tab === "reading" && files.has("md") ? <Reading path={files.get("md")!} /> : null}
          {tab === "structure" && files.has("jsonld") ? (
            <Structure path={files.get("jsonld")!} />
          ) : null}
          {tab === "graph" && files.has("jsonld") ? <Raw path={files.get("jsonld")!} /> : null}
        </>
      )}
    </>
  );
}

/** A hook rather than three copies: every tab fetches one published file and shows what happened. */
function usePublished<T>(path: string, read: (response: Response) => Promise<T>) {
  const [state, setState] = useState<
    { status: "loading" } | { status: "ready"; value: T } | { status: "failed"; error: string }
  >({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    fetchPublished(path)
      .then(read)
      .then((value) => {
        if (!cancelled) setState({ status: "ready", value });
      })
      .catch((error: unknown) => {
        if (!cancelled) setState({ status: "failed", error: String(error) });
      });
    return () => {
      cancelled = true;
    };
    // `read` is a stable module-level function at every call site; the path is what changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path]);

  return state;
}

const asText = (response: Response) => response.text();
const asJson = (response: Response) => response.json() as Promise<JsonLdDocument>;

function Reading({ path }: { path: string }) {
  const state = usePublished(path, asText);
  if (state.status === "loading") return <p className="muted">Loading the reading…</p>;
  if (state.status === "failed") return <p className="muted">Could not read /{path}.</p>;
  return (
    <div className="reading scroller">
      {/* The pipeline leaves page and marginal notes as HTML comments in the markdown; they are
          provenance for the files, not part of the reading, and `skipHtml` keeps them out. */}
      <Markdown remarkPlugins={[remarkGfm]} skipHtml>
        {state.value}
      </Markdown>
    </div>
  );
}

function Structure({ path }: { path: string }) {
  const state = usePublished(path, asJson);
  if (state.status === "loading") return <p className="muted">Loading the graph…</p>;
  if (state.status === "failed") return <p className="muted">Could not read /{path}.</p>;

  const graph = readGraph(state.value);
  if (graph.provisions.length === 0) {
    return <p className="muted">This expression's graph carries no provisions.</p>;
  }
  return (
    <>
      <p className="muted">
        {graph.size.toLocaleString()} nodes, rebuilt from <code>eli:has_part</code>.
      </p>
      <ProvisionTree provisions={graph.provisions} />
    </>
  );
}

function ProvisionTree({ provisions }: { provisions: Provision[] }) {
  return (
    <ul className="tree">
      {inPrintedOrder(provisions).map((provision) => (
        <li className="provision" key={provision.id}>
          <span className="pill">{provision.type}</span>
          {provision.number ? <span className="provision__number"> {provision.number}</span> : null}
          {provision.heading ? (
            <span className="provision__heading">{provision.heading}</span>
          ) : null}
          <span className="provision__id">{provision.id.split("/").pop()}</span>
          {provision.children.length > 0 ? <ProvisionTree provisions={provision.children} /> : null}
        </li>
      ))}
    </ul>
  );
}

function Raw({ path }: { path: string }) {
  const state = usePublished(path, asText);
  if (state.status === "loading") return <p className="muted">Loading…</p>;
  if (state.status === "failed") return <p className="muted">Could not read /{path}.</p>;
  return <pre className="raw">{state.value}</pre>;
}
