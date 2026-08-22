"""Structural analysis of legislative documents (HANDOFF 26).

Stage 1 of the legislation pipeline: stored PDF bytes become a layout-aware reading of the
document, an Arrangement of Sections read as its own artifact, and a body provision tree that
must match it (Gate L1). Nothing in this package fetches, mutates, or publishes anything.
"""
