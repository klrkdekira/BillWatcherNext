"""BillWatcherNext: a local-file pipeline from Parliament's bill PDFs to a published graph.

Three stages, one direction, no database and no server:

* `billwatcher.download` — the only stage that touches the network. Listings, then bills, then
  every document PDF, written to the corpus as plain files.
* `billwatcher.markdown` — reads each stored PDF locally into markdown, with no model in the loop.
* `billwatcher.graph` — reads a provision structure out of that markdown, renders Akoma Ntoso XML,
  gates it, and serialises the result as ELI JSON-LD and RDF N-Quads.

`billwatcher.publish` then projects the gate-passing part of the corpus into the static site tree
that GitHub Pages serves. Everything after `download` is offline and re-runnable: each step reads
files, writes files, and records what it did beside what it produced.
"""

from billwatcher.version import __version__

__all__ = ["__version__"]
