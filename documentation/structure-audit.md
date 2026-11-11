# Structure audit

Parser `AKN_VERSION` 1.6.0, gate `STRUCTURE_GATE_VERSION` 1.4.0, over every stored reading, without writing anything. "Recorded" is the verdict the last `convert-to-akn` run left beside the document; "would pass" is what the code in this checkout decides now.

| | |
| --- | --- |
| Readings audited | 2,479 |
| — with block geometry | 2,479 |
| Would pass Gate P1 | 2,200 |
| Recorded as passing | 2,200 |
| Would pass, recorded failing | 0 |
| Would fail, recorded passing | 0 |
| No recorded verdict | 0 |
| Parser raised | 0 |

## Blocking findings, by depth and kind

Documents carrying at least one finding of the family, and the total number of findings.

| Family | Documents | Findings |
| --- | --- | --- |
| `paragraph/sequence_gap` | 120 | 247 |
| `provision/sequence_order` | 75 | 131 |
| `provision/sequence_gap` | 72 | 84 |
| `provision/duplicate_eid` | 58 | 365 |
| `container/sequence_gap` | 52 | 79 |
| `paragraph/sequence_order` | 35 | 39 |
| `container/sequence_order` | 31 | 34 |
| `subsection/sequence_gap` | 27 | 32 |
| `container/duplicate_eid` | 22 | 100 |
| `subsection/duplicate_eid` | 14 | 47 |
| `paragraph/duplicate_eid` | 12 | 65 |
| `subparagraph/sequence_gap` | 10 | 10 |
| `subsection/sequence_order` | 9 | 13 |
| `document/low_text_coverage` | 3 | 3 |
| `provision/unanchored_run` | 3 | 3 |
| `subparagraph/duplicate_eid` | 3 | 8 |

## Would fail, recorded passing

None.

## Would pass, recorded failing

None.
