# Structure audit

Parser `AKN_VERSION` 1.5.0, gate `STRUCTURE_GATE_VERSION` 1.3.0, over every stored reading, without writing anything. "Recorded" is the verdict the last `convert-to-akn` run left beside the document; "would pass" is what the code in this checkout decides now.

| | |
| --- | --- |
| Readings audited | 2,479 |
| — with block geometry | 2,479 |
| Would pass Gate P1 | 1,972 |
| Recorded as passing | 1,971 |
| Would pass, recorded failing | 1 |
| Would fail, recorded passing | 0 |
| No recorded verdict | 0 |
| Parser raised | 0 |

## Blocking findings, by depth and kind

Documents carrying at least one finding of the family, and the total number of findings.

| Family | Documents | Findings |
| --- | --- | --- |
| `paragraph/sequence_gap` | 223 | 465 |
| `provision/sequence_order` | 155 | 265 |
| `paragraph/sequence_order` | 130 | 230 |
| `container/sequence_order` | 122 | 243 |
| `container/duplicate_eid` | 116 | 276 |
| `provision/duplicate_eid` | 113 | 796 |
| `provision/sequence_gap` | 108 | 153 |
| `container/sequence_gap` | 90 | 130 |
| `paragraph/duplicate_eid` | 68 | 420 |
| `subsection/sequence_gap` | 60 | 89 |
| `provision/unanchored_run` | 29 | 29 |
| `subsection/duplicate_eid` | 29 | 92 |
| `subsection/sequence_order` | 14 | 17 |
| `document/low_text_coverage` | 10 | 10 |
| `subparagraph/duplicate_eid` | 4 | 9 |

## Would fail, recorded passing

None.

## Would pass, recorded failing

- `dr-44-2007/doc-21109d59/v001`
