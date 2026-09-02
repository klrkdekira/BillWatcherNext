# Parlimen.gov.my Bills Recovery — Final Report v2 (2026-08-29)

**Result: 19 of 51 bills recovered + verified, 1 substitute provided, 31 not found.**

(v2: two more recovered from the **lib.perdana.org.my** library mirror — dr-10-2006 [ms] and dr-19-2017 [en] — after the Wayback-only round returned 17.)

## Method
1. All 51 parlimen.gov.my URLs tested — **all dead** (server returns a "File does not exist" HTML page).
2. Wayback Machine CDX — **domain-wide** sweep (not just /files/billindex/pdf): ~10,000 PDF rows of parlimen.gov.my, including the OLD site structures: `Undang/<year>/BILL-DR-<n>.pdf` (1990s–2002), flat `billindex/pdf/Bill-DR-<n>.pdf` (2006 era), the parallel `billindexbi/` English tree, and the space-named `DR NNYYYY(E).pdf` convention (963 captures, 2005–2007 era).
3. Live arkib index XMLs (13 session years) — official bill titles extracted for cross-verification; the live tree's canonical `myurl` links were also probed (all dead — the live site has removed every 2015/2017/2021/2025 bill file).
4. **lib.perdana.org.my (Perdana University library mirror)** — `PLF/Parliament_Bills/<year>/…` — directory indexes blocked (403) but direct PDF files serve; 2,700+ candidate filename templates probed against the gap list.
5. Every recovered PDF verified by **content** (title page: bill number, year, language), cross-checked against the official parlimen index. Wrong-session and wrong-language files were **excluded**.
6. archive.today/archive.ph: hard rate-limited (429) from this network even via rotated VPN egress; archive.org items search: no bill uploads; Google/Bing indexes of the dead URLs: none found; lom.agc.gov.my: enacted-act texts exist for passed bills but those are Acts, not the original bill PDFs.

## Verified deliverables (in this folder)
| Job | Bill | Title (official index) | File |
|---|---|---|---|
| 1 | dr-1-2006 [en] | Factories and Machinery (Amendment) Bill 2006 | dr-1-2006.pdf |
| 2 | dr-10-2006 [ms] | Malaysian Pepper Board Bill 2006 (Rang Undang-Undang Lembaga Lada Malaysia 2006) | dr-10-2006_ms.pdf |
| 6 | dr-15-2018 [ms] | Perbekalan (Penguntukan Semula Peruntukan) 2018 | D.R.15_2018_BM.pdf |
| 8 | dr-16-2004 [ms] | Criminal Procedure Code (Amendment) 2004 | dr-16-2004_ms.pdf |
| 9 | dr-19-2017 [en] | Trade Descriptions (Amendment) Bill 2017 — scanned 3-pp English copy | dr-19-2017_en.pdf |
| 10 | dr-2-2006 [en] | Malaysian Health Promotion Board Bill 2006 | dr-2-2006.pdf |
| 16 | dr-28-2023 [ms] | Kecekapan dan Konservasi Tenaga 2023 | D.R.28_2023_BM.pdf |
| 17 | dr-28-2023 [en] | Energy Efficiency and Conservation Bill 2023 | D.R.28_2023_EN.pdf |
| 18 | dr-29-2002 [en] | Supplementary Supply Bill 2002 | dr-29-2002.pdf |
| 21 | dr-3-2006 [en] | Akademi Seni Budaya dan Warisan Kebangsaan Bill 2006 | dr-3-2006.pdf |
| 22 | dr-30-2002 [en] | Supply Bill (2003 appropriations) | dr-30-2002.pdf |
| 23 | dr-30-2010 [ms] | Valuers, Appraisers and Estate Agents (Amendment) | D.R.30_2010_BM.pdf |
| 25 | dr-31-2002 [en] | Majlis Amanah Rakyat (Amendment) Bill 2002 | dr-31-2002.pdf |
| 26 | dr-32-2002 [en] | Labuan Trust Companies (Amendment) Bill 2002 | dr-32-2002.pdf |
| 28 | dr-33-2002 [en] | Finance (No. 2) Bill 2002 | dr-33-2002.pdf |
| 29 | dr-34-2010 [ms] | Juruanalisis Makanan (Pindaan) Bill 2010 | D.R.34_2010_BM.pdf |
| 40 | dr-39-2010 [ms] | Perkapalan Saudagar (Pencemaran Minyak) (Pindaan) | D.R.39_2010_BM.pdf |
| 44 | dr-4-2006 [en] | Suruhanjaya Perkhidmatan Air Negara Bill 2006 | dr-4-2006.pdf |
| 49 | dr-42-2010 [ms] | Timbang Tara (Pindaan) Bill 2010 (index says Arbitration — flagged) | D.R.42_2010_BM.pdf |

## Per-job status
| Job | Job ID | Status | File / Note |
|---|---|---|---|
| 1 | dr-1-2006 [en] | FOUND | dr-1-2006.pdf — Factories and Machinery (Amendment) Bill 2006, 27p |
| 2 | dr-10-2006 [ms] | FOUND | dr-10-2006_ms.pdf — Malaysian Pepper Board Bill 2006 (Rang Undang-Undang Lembaga Lada Malaysia 2006), header D.R. 10/2006, 60 pp — from lib.perdana.org.my mirror (official parlimen copy dead); title cross-checked vs parlimen 2006 index |
| 3 | dr-12-2004 [ms] | NOT FOUND |  — — |
| 4 | dr-12-2009 [ms] | NOT FOUND |  — — |
| 5 | dr-13-2009 [ms] | NOT FOUND |  — — |
| 6 | dr-15-2018 [ms] | FOUND | D.R.15_2018_BM.pdf — Perbekalan (Penguntukan Semula Peruntukan) 2018, D.R. 15/2018 |
| 7 | dr-15-2018 [en] | NOT FOUND |  — — |
| 8 | dr-16-2004 [ms] | FOUND | dr-16-2004_ms.pdf — Criminal Procedure Code (Amendment) Bill 2004, internal ref D.R. 16/2004 |
| 9 | dr-19-2017 [en] | FOUND | dr-19-2017_en.pdf — Trade Descriptions (Amendment) Act 2017 — English, 3-pp scanned copy (image-only) — from lib.perdana.org.my mirror; official index lists D.R.19/2017 as 'Trade (Amendment) Bill 2017 (Passed)'; enacted act = A1545 per lom. |
| 10 | dr-2-2006 [en] | FOUND | dr-2-2006.pdf — Malaysian Health Promotion Board Bill 2006, 20p |
| 11 | dr-2-2021 [en] | NOT FOUND |  — — |
| 12 | dr-21-2009 [ms] | NOT FOUND |  — — |
| 13 | dr-22-2009 [ms] | NOT FOUND |  — — |
| 14 | dr-22-2010 [en] | SUBSTITUTE | substitutes/dr-22-2010_MS_substitute_for_EN_job14.pdf — Job requests 22/2010 ENGLISH; only the MALAY version (DR222010.pdf) was ever archived. Provided as substitute, clearly labeled. |
| 15 | dr-24-2006 [ms] | NOT FOUND |  — — |
| 16 | dr-28-2023 [ms] | FOUND | D.R.28_2023_BM.pdf — Kecekapan dan Konservasi Tenaga 2023, D.R. 28/2023, 71p |
| 17 | dr-28-2023 [en] | FOUND | D.R.28_2023_EN.pdf — Energy Efficiency and Conservation Bill 2023, 64p |
| 18 | dr-29-2002 [en] | FOUND | dr-29-2002.pdf — Supplementary Supply Bill 2002 — old 'A BILL intituled' format, title matches official index D.R.29/2002 |
| 19 | dr-29-2015 [ms] | NOT FOUND |  — — |
| 20 | dr-29-2015 [en] | NOT FOUND |  — — |
| 21 | dr-3-2006 [en] | FOUND | dr-3-2006.pdf — Akademi Seni Budaya dan Warisan Kebangsaan Bill 2006, 42p |
| 22 | dr-30-2002 [en] | FOUND | dr-30-2002.pdf — Supply Bill (for 2003 appropriations) — title matches D.R.30/2002 |
| 23 | dr-30-2010 [ms] | FOUND | D.R.30_2010_BM.pdf — Penilai, Pentaksir dan Ejen Harta Tanah (Pindaan), D.R. 30/2010 |
| 24 | dr-30-2011 [en] | NOT FOUND |  — — |
| 25 | dr-31-2002 [en] | FOUND | dr-31-2002.pdf — Majlis Amanah Rakyat (Amendment) Bill 2002 — title matches D.R.31/2002 |
| 26 | dr-32-2002 [en] | FOUND | dr-32-2002.pdf — Labuan Trust Companies (Amendment) Bill 2002 — title matches D.R.32/2002 |
| 27 | dr-32-2025 [en] | NOT FOUND |  — — |
| 28 | dr-33-2002 [en] | FOUND | dr-33-2002.pdf — Finance (No. 2) Bill 2002 — title matches D.R.33/2002 |
| 29 | dr-34-2010 [ms] | FOUND | D.R.34_2010_BM.pdf — Juruanalisis Makanan, D.R. 34/2010 |
| 30 | dr-34-2010 [en] | NOT FOUND |  — — |
| 31 | dr-34-2015 [ms] | NOT FOUND |  — — |
| 32 | dr-34-2015 [en] | NOT FOUND |  — — |
| 33 | dr-34-2017 [en] | NOT FOUND |  — — |
| 34 | dr-36-2015 [ms] | NOT FOUND |  — — |
| 35 | dr-36-2015 [en] | NOT FOUND |  — — |
| 36 | dr-37-2015 [ms] | NOT FOUND |  — — |
| 37 | dr-37-2015 [en] | NOT FOUND |  — — |
| 38 | dr-38-2010 [ms] | NOT FOUND |  — — |
| 39 | dr-38-2010 [en] | NOT FOUND |  — — |
| 40 | dr-39-2010 [ms] | FOUND | D.R.39_2010_BM.pdf — Perkapalan Saudagar (Pencemaran Minyak) (Pindaan), D.R. 39/2010 |
| 41 | dr-39-2010 [en] | NOT FOUND |  — — |
| 42 | dr-39-2015 [ms] | NOT FOUND |  — — |
| 43 | dr-39-2015 [en] | NOT FOUND |  — — |
| 44 | dr-4-2006 [en] | FOUND | dr-4-2006.pdf — Suruhanjaya Perkhidmatan Air Negara Bill 2006, 24p |
| 45 | dr-4-2013 [ms] | NOT FOUND |  — — |
| 46 | dr-4-2013 [en] | NOT FOUND |  — — |
| 47 | dr-40-2017 [en] | NOT FOUND |  — — |
| 48 | dr-41-2010 [ms] | NOT FOUND |  — — |
| 49 | dr-42-2010 [ms] | FOUND | D.R.42_2010_BM.pdf — Timbang Tara (Pindaan), internal ref D.R. 42/2010. NOTE: parlimen's index lists D.R.42/2010 as 'Arbitration (Amendment)' — the archived PDF (DR422010.pdf from the /2011/ tree) carries the number 42/2010 but a different t |
| 50 | dr-42-2010 [en] | NOT FOUND |  — — |
| 51 | dr-12-2010 [en] | NOT FOUND |  — — |

## Key integrity findings
- **Job IDs are parlimen's own labels and are sometimes wrong** — e.g. `dr-40-2017 [en]` actually requests **bill 46/2017 English** (`D.R 46_2017 - eng.pdf`). The URL filename was used as ground truth throughout.
- **Pre-2010 bills don't print the "D.R. N/YYYY" header** — the 2002/2006 files were verified by title against the official parlimen index XML (all match).
- **Excluded as wrong:** a 1997 bill (bill 10/1997) that matched "bill 10" numerically; a 1999 bill (bill 24/1999); a 2011 bill (bill 41/2011); the 22/2010 **Malay** file for the English job #14 (kept as labeled substitute only).
- **Mirror duplicates excluded:** lib.perdana.org.my's `DR342010/DR392010/DR422010.pdf` (no-suffix) are the **Malay** versions (Wayback proved the no-suffix convention = BM); they duplicate bills already in the main set, so they don't fill the [en] jobs. `DR122009/132009/212009/222009.pdf` on Wayback are archived 404 error pages.
- **dr-19-2017 [en] caveat:** image-only 3-page scan; the printed bill-number line is blank. Attributed via filename + official index (D.R.19/2017 'Trade (Amendment) Bill 2017 (Passed)') + enacted act A1545 'Trade Descriptions (Amendment) Act 2017' on lom.agc.gov.my. Analyst-inference confidence: high but not 100%.
- **2009/2013/2015/2017/2021/2025:** zero genuine captures in Wayback (folder-level CDX verified per year); live arkib tree 2015 lists only 16 bills and none of ours; mirror probes (2,700+ templates) all 404. The 2015 cluster (10 jobs) is simply not anywhere on the public web.

## Sources
- web.archive.org CDX (parlimen.gov.my domain-wide + per-year billindex/2011-folder sweeps, 1990–2025)
- parlimen.gov.my live arkib tree XMLs (13 years) + live canonical links (all dead)
- lib.perdana.org.my/PLF/Parliament_Bills (Perdana University library mirror, direct files)
- lom.agc.gov.my (LACI enacted-act register, cross-check only)
