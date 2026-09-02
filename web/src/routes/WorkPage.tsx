import { Link, useParams } from "react-router";

import { CHAMBER_NAMES, FORMAT_NAMES, formatOf, MISSING_REASONS, publishedUrl } from "../catalogue";
import { useCatalogue } from "../CatalogueContext";
import { useLanguage } from "../LanguageContext";
import { LANGUAGE_NAMES, languagesOf, titleFor } from "../language";
import { NotFoundPage } from "./NotFoundPage";

/**
 * A Work: the bill as an abstract thing, independent of the language it is expressed in.
 *
 * This page exists because the identifier does. `/akn/my/bill/dr/2024/11` is a real directory in
 * the published tree with no file of its own, so GitHub Pages answers it with the 404 fallback and
 * the app renders this — which is what makes an FRBR Work IRI dereference in a browser.
 */
export function WorkPage() {
  const { chamber, year, number } = useParams();
  const state = useCatalogue();
  const { language } = useLanguage();
  const uri = `/akn/my/bill/${chamber}/${year}/${number}`;

  if (state.status === "loading") return <p className="muted">Loading…</p>;
  if (state.status === "failed") return <p className="muted">The catalogue could not be read.</p>;

  const work = state.catalogue.works.find((candidate) => candidate.uri === uri);
  if (!work) return <NotFoundPage />;

  return (
    <>
      <p className="crumbs">
        <Link to="/">All bills</Link> › {CHAMBER_NAMES[chamber ?? ""] ?? chamber} › {year}
      </p>
      <h1 className="display">{titleFor(work, language)}</h1>
      <p className="lede">
        <code>{work.uri}</code>
      </p>

      {Object.entries(work.titles).length > 1 ? (
        <>
          <h2 className="display">Titles</h2>
          <ul>
            {Object.entries(work.titles).map(([code, title]) => (
              <li key={code}>
                <span className={code === language ? "pill pill--accent" : "pill"}>
                  {LANGUAGE_NAMES[code] ?? code}
                </span>{" "}
                {title}
              </li>
            ))}
          </ul>
        </>
      ) : null}

      {work.missing ? (
        <div className="notice notice--bad">
          <p>
            <strong>This bill is missing from the corpus.</strong>{" "}
            {MISSING_REASONS[work.missing.reason] ??
              "Nothing of it could be published in this release."}
          </p>
          <p className="muted">
            It is listed here rather than omitted so that its absence is visible: this identifier is
            real, and a copy recovered later — from an archive, a mirror, or a paper file — can be
            imported against it.
          </p>
        </div>
      ) : null}

      {work.missing ? null : (
        <>
          <h2 className="display">Expressions</h2>
          <p className="muted">
            One per language this bill was read in. The language is a permanent part of the
            identifier, so a second reading in another language is a second expression rather than a
            revision — the same bill, addressed two ways.
          </p>
        </>
      )}

      {work.missing || languagesOf(work).includes(language) ? null : (
        <div className="notice notice--warn">
          <strong>Not read in {LANGUAGE_NAMES[language]}.</strong> Parliament publishes federal
          legislation in both languages, but this bill has only been read into the corpus in{" "}
          {languagesOf(work)
            .map((code) => LANGUAGE_NAMES[code])
            .join(" and ")}
          . That is a gap in the reading, not in the law.
        </div>
      )}

      {[...work.expressions]
        .toSorted((a, b) => Number(b.language === language) - Number(a.language === language))
        .map((expression) => (
          <section key={expression.uri}>
            <h3 className="display display--sub">
              <Link to={expression.uri}>{expression.title ?? expression.uri}</Link>{" "}
              <span className="pill pill--accent">
                {LANGUAGE_NAMES[expression.language] ?? expression.language}
              </span>
              {expression.reading?.suspect ? (
                <span className="pill pill--warn"> reading suspect</span>
              ) : null}
            </h3>
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
          </section>
        ))}
    </>
  );
}
