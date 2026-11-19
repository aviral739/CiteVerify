"""Pure-Python BM25 Okapi lexical retrieval engine."""

import math
import re
from typing import List, Tuple


class BM25Retriever:
    """Deterministic BM25 Okapi lexical search ranker.

    Parameters:
        k1 (float): Term frequency saturation parameter (default: 1.5).
        b (float): Document length normalization parameter (default: 0.75).
    """

    def __init__(self, corpus: List[str], k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.corpus_size = len(corpus)
        self.tokenized_corpus: List[List[str]] = [self._tokenize(doc) for doc in corpus]
        self.doc_lens: List[int] = [len(doc) for doc in self.tokenized_corpus]
        self.avg_doc_len = sum(self.doc_lens) / self.corpus_size if self.corpus_size > 0 else 0.0

        # Compute document frequencies for each term
        self.df: dict[str, int] = {}
        for doc in self.tokenized_corpus:
            unique_terms = set(doc)
            for term in unique_terms:
                self.df[term] = self.df.get(term, 0) + 1

        # Compute Inverse Document Frequency (IDF) with BM25 smoothing
        self.idf: dict[str, float] = {}
        for term, freq in self.df.items():
            # Standard Lucene/BM25 IDF: ln(1 + (N - n + 0.5) / (n + 0.5))
            self.idf[term] = math.log(1.0 + (self.corpus_size - freq + 0.5) / (freq + 0.5))

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """Normalize and tokenize text into lowercase alphanumeric words."""
        if not text:
            return []
        return re.findall(r"\b[a-zA-Z0-9_\-]{2,}\b", text.lower())

    def get_scores(self, query: str) -> List[float]:
        """Compute BM25 relevance scores for all documents in the corpus."""
        query_tokens = self._tokenize(query)
        scores = [0.0] * self.corpus_size
        if not query_tokens or self.corpus_size == 0 or self.avg_doc_len == 0.0:
            return scores

        for idx, doc_tokens in enumerate(self.tokenized_corpus):
            doc_len = self.doc_lens[idx]
            if doc_len == 0:
                continue

            # Compute term frequencies in this document
            tf_map: dict[str, int] = {}
            for token in doc_tokens:
                tf_map[token] = tf_map.get(token, 0) + 1

            doc_score = 0.0
            for token in query_tokens:
                if token not in tf_map:
                    continue
                tf = tf_map[token]
                idf = self.idf.get(token, 0.0)
                # BM25 term weighting formula
                numerator = tf * (self.k1 + 1.0)
                denominator = tf + self.k1 * (1.0 - self.b + self.b * (doc_len / self.avg_doc_len))
                doc_score += idf * (numerator / denominator)

            scores[idx] = doc_score

        return scores

    def search_top_k(self, query: str, top_k: int = 3) -> List[Tuple[int, float]]:
        """Return indices and scores of the top-k highest scoring passages."""
        scores = self.get_scores(query)
        scored_pairs = list(enumerate(scores))
        scored_pairs.sort(key=lambda x: x[1], reverse=True)
        return scored_pairs[:top_k]
