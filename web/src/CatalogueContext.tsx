import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

import { loadCatalogue, type Catalogue } from "./catalogue";

/**
 * The catalogue is fetched once and shared.
 *
 * `index.json` describes the whole corpus, and every page needs some of it — the list needs all
 * of it, a work page needs one entry, an expression page needs one entry's files. Fetching it per
 * route would re-download the whole catalogue on every navigation for no benefit.
 */
export type CatalogueState =
  | { status: "loading" }
  | { status: "ready"; catalogue: Catalogue }
  | { status: "failed"; error: string };

const Context = createContext<CatalogueState>({ status: "loading" });

export function CatalogueProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<CatalogueState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    loadCatalogue()
      .then((catalogue) => {
        if (!cancelled) setState({ status: "ready", catalogue });
      })
      .catch((error: unknown) => {
        if (!cancelled) setState({ status: "failed", error: String(error) });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return <Context.Provider value={state}>{children}</Context.Provider>;
}

export function useCatalogue(): CatalogueState {
  return useContext(Context);
}
