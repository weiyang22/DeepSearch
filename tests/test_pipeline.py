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

    def test_daily_selection_has_no_fixed_count_and_prioritizes_enterprise_genrec(self):
        today = dt.date.today().isoformat()
        papers = [
            Paper(id="company", title="Kimi K2 Technical Report", published=today, company="Kimi", content_type="company_report", abstract="foundation model post-training technical report"),
            Paper(id="enterprise-genrec", title="Generative Recommendation with Semantic ID", published=today, affiliations=["ByteDance"], abstract="generative recommendation semantic id"),
            Paper(id="academic-genrec", title="Generative Retrieval for Recommendation", published=today, abstract="generative retrieval for recommendation"),
            Paper(id="llm", title="Scaling Foundation Model Pretraining", published=today, abstract="large language model pretraining scaling law"),
            Paper(id="app", title="Using LLM for Healthcare", published=today, abstract="healthcare application using llm for diagnosis"),
            Paper(id="science", title="A Foundation Model of Wavefunctions", published=today, abstract="foundation model for chemical bond breaking"),
        ]
        ranked = prepare_candidates(papers, self.config)
        selected = choose_daily_picks(ranked, self.config)
        self.assertEqual(len(selected), 4)
        self.assertNotIn("app", [item.id for item in ranked])
        self.assertNotIn("science", [item.id for item in ranked])
        self.assertGreater(next(item.score for item in ranked if item.id == "enterprise-genrec"), next(item.score for item in ranked if item.id == "academic-genrec"))


if __name__ == "__main__":
    unittest.main()
