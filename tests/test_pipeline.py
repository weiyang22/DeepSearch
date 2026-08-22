import datetime as dt
import unittest

from deepsearch.config import load_config
from deepsearch.models import Paper
from deepsearch.ranking import choose_daily_picks, has_ab_experiment, infer_tags, prepare_candidates
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
        paper = Paper(id="a", title="Generative Recommendation with Semantic IDs", abstract="An online A/B test validates the system.")
        self.assertIn("GenRec", infer_tags(paper))
        self.assertIn("Semantic ID", infer_tags(paper))
        self.assertTrue(has_ab_experiment(paper))

    def test_daily_selection_has_no_fixed_count_and_prioritizes_enterprise_genrec(self):
        today = dt.date.today().isoformat()
        papers = [
            Paper(id="company", title="Kimi K2 Technical Report", published=today, company="Kimi", content_type="company_report", abstract="foundation model post-training technical report"),
            Paper(id="company-bench", title="Kimi PerceptionBench", published=today, company="Kimi", content_type="company_report", abstract="large language model evaluation benchmark technical report"),
            Paper(id="enterprise-genrec", title="Generative Recommendation with Semantic ID", published=today, affiliations=["ByteDance"], abstract="generative recommendation semantic id with an online A/B test"),
            Paper(id="academic-genrec", title="Generative Retrieval for Recommendation", published=today, abstract="generative retrieval for recommendation"),
            Paper(id="enterprise-llm", title="Scaling Foundation Model Pretraining", published=today, affiliations=["Google"], abstract="large language model pretraining scaling law"),
            Paper(id="academic-llm", title="Academic Foundation Model Pretraining", published=today, abstract="large language model pretraining scaling law"),
            Paper(id="app", title="Using LLM for Healthcare", published=today, abstract="healthcare application using llm for diagnosis"),
            Paper(id="science", title="A Foundation Model of Wavefunctions", published=today, abstract="foundation model for chemical bond breaking"),
        ]
        ranked = prepare_candidates(papers, self.config)
        selected = choose_daily_picks(ranked, self.config)
        self.assertEqual(len(selected), 3)
        self.assertNotIn("app", [item.id for item in ranked])
        self.assertNotIn("science", [item.id for item in ranked])
        self.assertNotIn("academic-genrec", [item.id for item in ranked])
        self.assertNotIn("academic-llm", [item.id for item in ranked])
        self.assertNotIn("company-bench", [item.id for item in ranked])
        self.assertIn("A/B 实验", next(item.tags for item in ranked if item.id == "enterprise-genrec"))

    def test_retention_window_covers_the_past_year(self):
        within_window = (dt.date.today() - dt.timedelta(days=364)).isoformat()
        outside_window = (dt.date.today() - dt.timedelta(days=366)).isoformat()
        papers = [
            Paper(
                id="within",
                title="Industrial Generative Recommendation",
                published=within_window,
                affiliations=["ByteDance"],
                abstract="Generative recommendation evaluated with an online A/B test.",
            ),
            Paper(
                id="outside",
                title="Older Industrial Generative Recommendation",
                published=outside_window,
                affiliations=["ByteDance"],
                abstract="Generative recommendation evaluated with an online A/B test.",
            ),
        ]
        ranked = prepare_candidates(papers, self.config)
        self.assertIn("within", [item.id for item in ranked])
        self.assertNotIn("outside", [item.id for item in ranked])


if __name__ == "__main__":
    unittest.main()
