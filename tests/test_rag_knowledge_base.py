import unittest
from pathlib import Path

from tools.rag_knowledge_base import (
    build_candidate_query,
    chunk_page_text,
    retrieve_candidate_evidence,
    source_files,
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


if __name__ == "__main__":
    unittest.main()
