import { useMemo, useState } from "react";
import { Link } from "react-router";

import { CHAMBER_NAMES, FORMAT_NAMES, formatOf, identify, type Work } from "../catalogue";
import { useCatalogue } from "../CatalogueContext";
import { useLanguage } from "../LanguageContext";
import { choose, languagesOf, LANGUAGE_NAMES, titleFor, type Language } from "../language";

/** How many works to render at once. The corpus is ~1,200 rows; a browser renders 200 instantly. */
const PAGE = 200;

export function CataloguePage() {
  const state = useCatalogue();
  const { language } = useLanguage();
  const [query, setQuery] = useState("");
  const [onlyPreferred, setOnlyPreferred] = useState(false);
  const [year, setYear] = useState("");
  const [chamber, setChamber] = useState("");
  const [shown, setShown] = useState(PAGE);

  const catalogue = state.status === "ready" ? state.catalogue : null;

  const years = useMemo(() => {
    const found = new Set<number>();
    for (const work of catalogue?.works ?? []) {
      const identity = identify(work);
      if (identity) found.add(identity.year);
    }
    return [...found].toSorted((a, b) => b - a);
  }, [catalogue]);

  const matches = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (catalogue?.works ?? []).filter((work) => {
      const identity = identify(work);
      if (year && identity?.year !== Number(year)) return false;
      if (chamber && identity?.chamber !== chamber) return false;
      if (onlyPreferred && !languagesOf(work).includes(language)) return false;
      if (!needle) return true;
      // Every title the bill has, not just the one on screen: a reader searching in English for a
      // bill they are reading in Malay is searching for the same bill.
      return (
        Object.values(work.titles).some((title) => title.toLowerCase().includes(needle)) ||
        work.uri.toLowerCase().includes(needle)
      );
    });
  }, [catalogue, query, year, chamber, onlyPreferred, language]);

  if (state.status === "loading") return <p className="muted">Loading the catalogue…</p>;
  if (state.status === "failed") {
    return (
      <div className="notice notice--bad">
        <p>
          <strong>The catalogue could not be read.</strong> {state.error}
        </p>
        <p className="muted">
          Nothing is published yet if <code>index.json</code> is missing — run{" "}
          <code>make publish</code>.
        </p>
      </div>
    );
  }

  const expressions = state.catalogue.works.reduce(
    (total, work) => total + work.expressions.length,
    0,
  );
  const missing = state.catalogue.works.filter((work) => work.missing).length;

  return (
    <>
      <p className="eyebrow">Parlimen Malaysia · Parliament of Malaysia</p>
      <h1 className="display">Bills of the Malaysian Parliament</h1>
      <p className="lede">
        Every bill below was downloaded as its published PDF, read into markdown locally, and
        serialised into a semantic knowledge graph on a stable FRBR identifier. The files are the
        product: this page is only a reader for them.
      </p>

      <ul className="stats">
        <li className="stat">
          <span className="stat__value">{state.catalogue.works.length.toLocaleString()}</span>
          <span className="stat__label">Works</span>
        </li>
        <li className="stat">
          <span className="stat__value">{expressions.toLocaleString()}</span>
          <span className="stat__label">Expressions</span>
        </li>
        <li className="stat">
          <span className="stat__value">{state.catalogue.representations.length}</span>
          <span className="stat__label">
            {state.catalogue.representations.map((r) => FORMAT_NAMES[r] ?? r).join(", ")}
          </span>
        </li>
        <li className="stat">
          <span className="stat__value">{state.catalogue.publication_mode}</span>
          <span className="stat__label">Publication mode</span>
        </li>
        {missing > 0 ? (
          <li className="stat">
            <span className="stat__value">{missing.toLocaleString()}</span>
            <span className="stat__label">Missing</span>
          </li>
        ) : null}
      </ul>

      {state.catalogue.publication_mode === "metadata" ? (
        <div className="notice notice--warn">
          <strong>Structure only.</strong> This release publishes provision numbers, headings and
          the relationships between them — not the text of the provisions themselves.
        </div>
      ) : null}

      <div className="filters">
        <label className="field field--wide">
          <span className="field__label">Search</span>
          <input
            type="search"
            value={query}
            placeholder="Title or identifier"
            onChange={(event) => {
              setQuery(event.target.value);
              setShown(PAGE);
            }}
          />
        </label>
        <label className="field">
          <span className="field__label">Year</span>
          <select
            value={year}
            onChange={(event) => {
              setYear(event.target.value);
              setShown(PAGE);
            }}
          >
            <option value="">All years</option>
            {years.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field__label">Chamber</span>
          <select
            value={chamber}
            onChange={(event) => {
              setChamber(event.target.value);
              setShown(PAGE);
            }}
          >
            <option value="">Both chambers</option>
            {Object.entries(CHAMBER_NAMES).map(([code, name]) => (
              <option key={code} value={code}>
                {name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field__label">Language</span>
          <select
            value={onlyPreferred ? "preferred" : ""}
            onChange={(event) => {
              setOnlyPreferred(event.target.value === "preferred");
              setShown(PAGE);
            }}
          >
            <option value="">Any language</option>
            {/* Not "hide the rest" — "show me only what I can actually read". A bill Parliament
                published in both languages but that was only read in one is a gap in the corpus,
                and a reader looking for their language should be able to see just the bills that
                have it. */}
            <option value="preferred">Read in {LANGUAGE_NAMES[language]}</option>
          </select>
        </label>
        <p className="filters__count">
          {matches.length.toLocaleString()} of {state.catalogue.works.length.toLocaleString()}
        </p>
      </div>

      {matches.length === 0 ? (
        <p className="muted">No bill matches those filters.</p>
      ) : (
        <>
          <ul className="works">
            {matches.slice(0, shown).map((work) => (
              <WorkRow key={work.uri} work={work} language={language} />
            ))}
          </ul>
          {shown < matches.length ? (
            <p>
              <button
                className="button"
                type="button"
                onClick={() => setShown((count) => count + PAGE)}
              >
                Show {Math.min(PAGE, matches.length - shown)} more
              </button>
            </p>
          ) : null}
        </>
      )}
    </>
  );
}

/**
 * One bill, linked straight to the expression the reader wants to read.
 *
 * The title and the link target both follow the chosen language, and the row says which languages
 * this bill was read in — so a reader can see at a glance that a bill exists in both, or only in
 * one, before clicking into it.
 */
function WorkRow({ work, language }: { work: Work; language: Language }) {
  const identity = identify(work);
  const formats = new Set(work.expressions.flatMap((e) => e.files.map(formatOf)));
  const suspect = work.expressions.some((e) => e.reading?.suspect);
  const chosen = choose(work, language);
  const languages = languagesOf(work);

  return (
    <li className="work">
      <span className="work__number">
        {identity ? `${identity.chamber.toUpperCase()} ${identity.number}/${identity.year}` : "—"}
      </span>
      <span className="work__title">
        {/* Straight to the reading, not to the Work page: a reader who has chosen a language has
            already answered the only question the Work page would ask them. A missing bill has no
            reading to go to, so its identifier leads to the Work page, which says why. */}
        <Link to={chosen?.expression.uri ?? work.uri}>{titleFor(work, language)}</Link>
      </span>
      <span className="work__badges">
        {work.missing ? <span className="pill pill--bad">missing</span> : null}
        {languages.map((code) => (
          <span
            className={code === language ? "pill pill--accent" : "pill"}
            key={code}
            title={LANGUAGE_NAMES[code]}
          >
            {code}
          </span>
        ))}
        {[...formats].toSorted().map((format) => (
          <span className="pill" key={format}>
            {FORMAT_NAMES[format] ?? format}
          </span>
        ))}
        {suspect ? <span className="pill pill--warn">reading suspect</span> : null}
      </span>
    </li>
  );
}
