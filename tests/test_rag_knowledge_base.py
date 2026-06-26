import unittest
from pathlib import Path

from tools.rag_knowledge_base import (
    build_candidate_query,
    chunk_page_text,
    merge_search_hits,
    retrieve_candidate_evidence,
    source_files,
    vector_literal,
    years_covered,
)


class RagKnowledgeBaseTests(unittest.TestCase):
    def test_source_files_only_returns_pdf_documents(self) -> None:
        root = Path("knowledge/rag_sources")
        files = source_files(root, limit=5)
        self.assertTrue(files)
        for item in files:
            self.assertEqual(item.suffix.lower(), ".pdf")
            self.assertFalse(item.name.endswith(":Zone.Identifier"))

    def test_chunk_page_text_splits_large_page(self) -> None:
        text = ("mazda cx30 guardabarro izquierdo 2021 2022 2023 " * 80).strip()
        chunks = chunk_page_text(2, text, max_chars=180, overlap=20)
        self.assertGreater(len(chunks), 2)
        self.assertTrue(all(chunk["page_start"] == 2 for chunk in chunks))
        self.assertTrue(all(chunk["content_normalized"] for chunk in chunks))

    def test_years_covered_parses_ranges_and_single_years(self) -> None:
        covered = years_covered("Mazda CX30 2021-2023 con revision 2025")
        self.assertIn(2021, covered)
        self.assertIn(2022, covered)
        self.assertIn(2023, covered)
        self.assertIn(2025, covered)

    def test_build_candidate_query_contains_vehicle_and_candidate_tokens(self) -> None:
        query = build_candidate_query(
            quote_context={"marca": "KIA", "linea": "SPORTAGE", "ano": 2017},
            part={"part_name": "Liquido refrigerante galon", "requested_reference": None},
            candidate={
                "product_name": "Refrigerante base agua",
                "reference": "REF-77",
                "brand": "Impocali",
                "category_name": "Refrigeracion",
            },
        )
        self.assertIn("kia", query)
        self.assertIn("sportage", query)
        self.assertIn("refrigerante", query)

    def test_retrieve_candidate_evidence_returns_no_evidence_without_db(self) -> None:
        result = retrieve_candidate_evidence(
            quote_context={"marca": "KIA", "linea": "SPORTAGE", "ano": 2017},
            part={"part_name": "Liquido refrigerante galon", "requested_reference": None},
            candidate={"product_name": "Refrigerante base agua"},
            database_url=None,
            limit=2,
        )
        self.assertEqual(result["verdict"], "no_evidence")
        self.assertEqual(result["citations"], [])

    def test_vector_literal_serializes_embedding(self) -> None:
        serialized = vector_literal([0.1, -0.25, 3])
        self.assertEqual(serialized, "[0.10000000,-0.25000000,3.00000000]")

    def test_merge_search_hits_marks_hybrid_results(self) -> None:
        text_hits = [
            {
                "document_id": "doc-1",
                "chunk_id": "chunk-1",
                "title": "Catalogo A",
                "file_path": "knowledge/rag_sources/a.pdf",
                "page_start": 12,
                "page_end": 12,
                "chunk_index": 0,
                "content": "guardabarro izquierdo mazda cx30 2022",
                "score": 0.8,
            }
        ]
        vector_hits = [
            {
                "document_id": "doc-1",
                "chunk_id": "chunk-1",
                "title": "Catalogo A",
                "file_path": "knowledge/rag_sources/a.pdf",
                "page_start": 12,
                "page_end": 12,
                "chunk_index": 0,
                "content": "guardabarro izquierdo mazda cx30 2022",
                "score": 0.92,
            },
            {
                "document_id": "doc-2",
                "chunk_id": "chunk-9",
                "title": "Catalogo B",
                "file_path": "knowledge/rag_sources/b.pdf",
                "page_start": 7,
                "page_end": 7,
                "chunk_index": 3,
                "content": "pieza compatible familia suv",
                "score": 0.73,
            },
        ]

        merged = merge_search_hits(text_hits, vector_hits, limit=3)

        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0]["retrieval_mode"], "hybrid")
        self.assertGreater(merged[0]["score"], merged[1]["score"])
        self.assertEqual(merged[1]["retrieval_mode"], "vector")


if __name__ == "__main__":
    unittest.main()
