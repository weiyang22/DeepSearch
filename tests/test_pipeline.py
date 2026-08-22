import datetime as dt
import unittest

from deepsearch.config import load_config
from deepsearch.models import Paper
from deepsearch.ranking import choose_daily_picks, infer_tags, prepare_candidates
from deepsearch.sources import deduplicate


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config("config.toml")

    def test_deduplicates_by_doi_and_prefers_richer_record(self):
        sparse = Paper(id="a", title="Same paper", doi="10.1/demo", abstract="short")
        rich = Paper(id="b", title="Same paper", doi="10.1/demo", abstract="long " * 100, pdf_url="https://example.com/a.pdf")
        result = deduplicate([sparse, rich])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].id, "b")

    def test_infers_genrec_and_semantic_id_tags(self):
        paper = Paper(id="a", title="Generative Recommendation with Semantic IDs")
        self.assertIn("GenRec", infer_tags(paper))
        self.assertIn("Semantic ID", infer_tags(paper))

    def test_daily_selection_balances_company_and_genrec(self):
        today = dt.date.today().isoformat()
        papers = [
            Paper(id="company", title="Official LLM Technical Report", published=today, company="Kimi", content_type="company_report", abstract="large language model technical report"),
            Paper(id="genrec", title="Generative Recommendation with Semantic ID", published=today, abstract="generative recommendation semantic id"),
            Paper(id="llm", title="Large Language Model Study", published=today, abstract="large language model"),
            Paper(id="other", title="LLM Recommendation", published=today, abstract="llm recommendation"),
        ]
        ranked = prepare_candidates(papers, self.config)
        selected = choose_daily_picks(ranked, 4)
        self.assertEqual(len(selected), 4)
        self.assertTrue(any(item.company for item in selected))
        self.assertTrue(any("GenRec" in item.tags for item in selected))


if __name__ == "__main__":
    unittest.main()
