# Query expansion and the paraphrase-retrieval gap

Paraphrased questions (written to share few words with the manual) were the weakest retrieval result: MRR 0.633
with the original relevance floor of -4.0. What was tried, on the 50-question paraphrase set (the 1,204-chunk
evaluation index, hybrid + rerank, MRR / recall@1):

| Change | Paraphrase set | Other sets | Kept? |
|---|---|---|---|
| Relevance floor -4.0 -> -10.0 | 0.633 -> 0.730 / 0.66 | no loss on any (see real-document-evaluation.md) | yes, default |
| Embedding model MiniLM-L6 -> bge-small-en-v1.5 | 0.730 -> 0.748 / 0.68 | main 0.959 -> 0.940, others within 0.002 | no: noise, and a re-index |
| Reranker bge-reranker-base | 0.705 (one set only) | stopped: about 40 s per question on CPU | no |
| Reranker blended with dense score | 0.766 | real documents 0.950 -> 0.804 | no |
| Hypothetical-passage expansion of the dense query | 0.730 -> 0.763 / 0.70 | sampled set 0.853 = 0.853, guide set 0.861 = 0.861 | opt-in |

## The expansion step

`QUERY_EXPANSION=hyde` (default `off`) makes the configured LLM write a two- or three-sentence passage that could
appear in a technical manual and answer the question; the dense search embeds the question plus that passage.
BM25 and the cross-encoder still use the user's own words, so only the candidate set can change. Any failure,
timeout (`QUERY_EXPANSION_TIMEOUT_SECONDS`, default 20) or empty answer falls back to the plain query.
It costs one LLM call per search (about 5 s with `qwen2.5:7b` on a laptop CPU).

Reproduce: `scripts/generate_query_expansions.py` (Ollama, standard library) writes the passages;
`python -m evaluation.query_expansion_eval` compares the variants.

## Honest reading

- +0.033 MRR on 50 questions is two questions moving from rank 2-3 to rank 1. It points the right way on one set
  and changes nothing on two others; it is not strong evidence, which is why it is off by default.
- Most of the remaining paraphrase misses are not retrieval failures in the usual sense. The questions were
  written for five small synthetic manuals but are now searched among 1,204 chunks that include a 321-page real
  guide. Of the 17 questions whose first result is not the target section, 10 put a guide chunk first (for
  example the "machine is shaking" question retrieves the guide's vibration chapter, which is a sensible
  answer) and 7 put a sibling section from another manual first (the target is then ranked 2nd to 7th, or
  missing). The metric counts only the section the question was written for.
- The reranker (a small MS MARCO cross-encoder) is the limiting stage: the right passage is in the candidate pool
  for 48 of 50 questions but is ranked first for only 33. A larger reranker was far too slow on CPU.
