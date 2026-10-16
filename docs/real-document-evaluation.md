# Retrieval on real documents

The original evaluation corpus is four short manuals (about 1,500 words, three of them synthetic). That is too small
to tell the retrieval stages apart, so on 2026-10-13 five real public documents were added, the extractor's weakness
on them was measured, and then fixed.

## Documents

US Department of Energy tip sheets (US government publications), downloaded with `scripts/download_real_manuals.py`
(fixed URLs, SHA-256 checked). They are not stored in git. About 6,200 words; 70 chunks before the fix, 67 after.

| File | Topic |
|---|---|
| `test_pumping_system__pumping_systemts4.pdf` | Pumping Systems Tip Sheet #4, test for pumping system efficiency (2005) |
| `efficient_centrifug_pumps.pdf` | Tip Sheet #3, selecting an energy-efficient centrifugal pump (2005) |
| `match_pumps_to_system.pdf` | Tip Sheet #6, matching pumps to system requirements (2005) |
| `reduce_pumping_costs.pdf` | Tip Sheet #9, optimum pipe sizing (2005) |
| `extend_motor_operlife_motor_systemts3.pdf` | Motor Systems Tip Sheet #3, extending motor life (2012) |

These are energy-efficiency guides with some maintenance content, not maintenance manuals, and the figures are old.

## Method

`data/evaluation/retrieval_questions_real.json`: 63 answerable questions (26 phrased close to the source, 37 paraphrased).
Each question names a source file and one or more short evidence phrases copied from the document. A retrieved chunk
counts as the right answer when it comes from that file and contains every phrase (case and whitespace ignored).
Only the first matching chunk per question counts.

Section labels cannot be used as ground truth here: before the fix the extractor produced labels such as `5308 x P` or
`FOR A STRONG AMERICA` for these files. Anchoring on evidence text avoids depending on those labels.

The questions and phrases were fixed before the extractor change and not edited afterwards, so the before and after runs
use identical ground truth. Six phrases had been shortened because the old extractor split the sentence across columns
(for example "root cause failure analysis" arrived as "root ... cause failure analysis" with sidebar text in between).

Run: `docker compose run --rm backend python -m evaluation.retrieval_ablation data/evaluation/retrieval_questions_real.json`

## The problem

The extractor used pdfplumber's line grouping on the whole page, so a sidebar and the body text that share a baseline
came out as one line. Sentences from two unrelated paragraphs were interleaved, section labels were fragments of
formulas and contact details, and chunks mixed sidebar and body text.

## The fix

`_find_column_bands` in `app/ingestion/pdf_extractor.py`. Text is cut into blocks at blank horizontal strips; a band is
the longest run of blocks whose combined footprint still leaves a vertical gutter of at least 12 pt with 4+ lines and
80+ characters of text on every side. Only bands are split into columns. Full-width titles and footers stay in reading
order, and single-column pages take the original code path. Checks: no text lost on the five files (extracted
characters are 100.0 to 100.4% of the characters in the PDF), four new unit tests (two fail on the old extractor, two
guard against false splits), and the backend suite passes apart from one test that also fails on the original code in
this environment.

## Results (2026-10-13, CPU)

63 questions on the real documents, before the fix (114-chunk index) and after (111-chunk index):

| Configuration | MRR before | MRR after | Recall@1 before | Recall@1 after |
|---|---|---|---|---|
| BM25 only | 0.768 | 0.882 | 0.667 | 0.825 |
| Dense only | 0.609 | 0.719 | 0.476 | 0.571 |
| Dense + BM25 + RRF | 0.722 | 0.830 | 0.587 | 0.714 |
| Dense + BM25 + RRF + reranker | 0.881 | **0.952** | 0.857 | **0.937** |

After the fix, recall@5 is 0.968 for the reranked and hybrid configurations. Close to the source (26 questions):
reranked MRR 0.981, recall@1 0.962. Paraphrased (37): reranked MRR 0.932, recall@1 0.919.

The other two sets were re-run on the same index. The 53-question set: reranked MRR 0.969 and recall@1 0.962 at every
stage of this work; hybrid RRF 0.953 on the original 44 chunks, 0.915 with the unfixed real documents added, 0.962
after the fix; dense-only 0.903, 0.864, 0.855. The 50 paraphrased questions: reranked MRR 0.670 throughout.

## What to take from this, and what not to

- The fix moved every configuration, with the largest gain for BM25 and plain hybrid: broken chunks hurt lexical and
  embedding retrieval alike. The reranker still gives the best result, but its margin over BM25 shrank from 0.11 to
  0.07 MRR.
- 63 questions is small: one question is about 1.6 points of recall. Treat gains under about 5 points as noise.
- I wrote these questions and chose the evidence phrases, so this is not independent. Many answers are numbers, which
  favours lexical matching. Five documents from one publisher is a narrow corpus.
- The fix was developed while looking at these same five files, so some tuning to them is possible. The thresholds are
  generic (12 pt gutter, 4 lines, 80 characters), but they were not tested on other multi-column documents.
- Retrieval only. No generation or abstention was measured on these documents.
- Not fixed: repeated boilerplate (contact details, program blurbs) is still chunked and indexed; tables, text boxes
  and figure text are not modelled; a few chunks keep labels such as `PLEASE CONTACT:`.

## Update 2026-10-16: a 321-page guide, boilerplate removal, a larger index

Three changes, measured together because they share one index:

- The PNNL/DOE *Operations & Maintenance Best Practices Guide, Release 3.0* (321 pages) was added to the evaluation
  index (`scripts/download_real_manuals.py`, SHA-256 checked). The index grew from 111 to 1,204 chunks.
- `_drop_publisher_boilerplate` removes each page's closing "About DOE", "PLEASE CONTACT" and report-number panel.
- Indexing the guide exposed two defects, both fixed: `ocr_pages` rendered every page between the first and last
  scanned page at once (pages 4 to 321, over 4.5 GB, killed by the OS), and the extractor kept every parsed character
  of every page in memory. OCR now renders one scanned page at a time (16 pages, 7 s, under 900 MB).

New question set `data/evaluation/retrieval_questions_om_guide.json`: 24 questions (12 direct, 12 paraphrased)
anchored to evidence phrases. The phrases were checked to exist in the extracted chunks before any retrieval run;
one was replaced because the original sat across interleaved columns and matched no chunk. No question was changed
after seeing results.

| Configuration | MRR | Recall@1 | Recall@3 |
|---|---|---|---|
| BM25 only | 0.809 | 0.750 | 0.875 |
| Dense only | 0.703 | 0.542 | 0.875 |
| Dense + BM25 + RRF | **0.896** | **0.833** | 0.958 |
| Dense + BM25 + RRF + reranker | 0.861 | 0.750 | **1.000** |

The reranker finds the passage in the top three every time but puts it first less often than plain hybrid fusion.
With 24 questions, one question is 4 points of recall, so the 0.035 MRR gap between hybrid and reranked is within noise.

The earlier sets re-run on the 1,204-chunk index (reranked MRR / recall@1):

| Set | 111 chunks | 1,204 chunks |
|---|---|---|
| 53 questions (main) | 0.969 / 0.962 | 0.959 / 0.943 |
| 50 paraphrased | 0.670 / n.r. | 0.633 / 0.600 (0.730 / 0.660 after the floor change below) |
| 63 real DOE questions | 0.952 / 0.937 | 0.944 / 0.921 (0.950 / 0.921 after the floor change below) |

Small drops are what a 10x larger index should cause, but the boilerplate filter changed the DOE chunks at the same
time, so the two effects are not separated.

## Update 2026-10-16: relevance floor lowered from -4.0 to -10.0

Why the paraphrase score was low: in 48 of 50 paraphrased questions the right passage was already among the fused
candidates, but the reranker scored it below -4.0 for 14 of them, so the floor removed it entirely. The ranking was
not the main problem; the cut-off was. Variants tried on the same index (MRR, paraphrased set / 24-question guide set /
63 real DOE set / 53 main set), with the original reranker and the floor off unless stated:

| Variant | Paraphrased | Guide | Real DOE | Main |
|---|---|---|---|---|
| Old floor (-4.0) | 0.633 | 0.861 | 0.944 | 0.959 |
| No floor | 0.732 | 0.861 | 0.950 | 0.959 |
| Section heading prepended for the reranker | 0.740 | 0.840 | 0.952 | 0.981 |
| RRF of reranker, dense and BM25 ranks | 0.634 | 0.900 | 0.807 | 0.906 |
| Reranker blended with dense score (0.5 / 0.5) | 0.766 | 0.859 | 0.804 | 0.892 |

Blending gave the best paraphrase score but cost 0.14 MRR on the real documents, so it was not adopted. Removing the
floor never lost more than 0.006 MRR on any set and was the only change that helped without hurting. Shipped value:
-10.0, which keeps the right passage in 92% of paraphrased questions (versus 68% at -4.0). Measured with it:
paraphrased 0.730, real DOE 0.950, main 0.959, guide 0.861.

`BAAI/bge-reranker-base` (1.1 GB) was also tried. It finished only the paraphrased set in about 35 minutes of CPU time
(MRR 0.705, below the original reranker with the floor removed) and was stopped.

The cost: with this reranker no cut-off separated answerable from unanswerable questions reliably (see the cut-off
benchmark in the README), so lowering the floor trades some unanswerable-question blocking for recall. Answer-level
abstention was not re-run.
