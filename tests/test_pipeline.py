import datetime as dt
import unittest

from deepsearch.config import load_config
from deepsearch.models import Paper
from deepsearch.ranking import choose_daily_picks, has_ab_experiment, infer_tags, prepare_candidates
from deepsearch.sources import (
    _github_report_url,
    _has_human_institution_author,
    _looks_like_foundation_model_report,
    _repo_matches_model_family,
    classify_company,
    deduplicate,
)


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

    def test_recognizes_kimi_k3_relative_full_report(self):
        readme = '<a href="k3_tech_report.pdf">Full Report</a> Kimi K3 mixture of experts'
        self.assertTrue(_looks_like_foundation_model_report(readme.lower()))
        self.assertEqual(
            _github_report_url("MoonshotAI", "Kimi-K3", "main", readme),
            "https://github.com/MoonshotAI/Kimi-K3/blob/main/k3_tech_report.pdf",
        )

    def test_classifies_google_deepmind_as_focus_company(self):
        paper = Paper(
            id="deepmind",
            title="Scaling a Foundation Model",
            affiliations=["Google DeepMind"],
        )
        classify_company(paper, self.config)
        self.assertEqual(paper.company, "Google DeepMind")
        self.assertEqual(self.config.github_orgs["Google DeepMind"], "google-deepmind")
        self.assertEqual(self.config.openalex_institutions["Google DeepMind"], "I4210090411")

    def test_ignores_model_names_as_institution_authors(self):
        model_authorship = {
            "authorships": [{
                "author": {"display_name": "Gemini 3.1 (Flash)"},
                "institutions": [{"id": "https://openalex.org/I4210090411"}],
            }]
        }
        human_authorship = {
            "authorships": [{
                "author": {"display_name": "A. Researcher"},
                "institutions": [{"id": "https://openalex.org/I4210090411"}],
            }]
        }
        self.assertFalse(_has_human_institution_author(model_authorship, "I4210090411"))
        self.assertTrue(_has_human_institution_author(human_authorship, "I4210090411"))

    def test_mainstream_model_families_and_repo_prefilter(self):
        expected = {
            "OpenAI": "GPT",
            "Anthropic": "Claude",
            "Google DeepMind": "Gemini",
            "Alibaba Qwen": "Qwen",
            "Xiaomi MiMo": "MiMo",
        }
        for company, family in expected.items():
            self.assertIn(family, self.config.model_families[company])
        self.assertTrue(_repo_matches_model_family("Xiaomi MiMo", "MiMo-V2", "official model", self.config))
        self.assertFalse(_repo_matches_model_family("OpenAI", "openai-python", "API client", self.config))

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

    def test_candidates_are_sorted_newest_first_even_when_older_scores_higher(self):
        today = dt.date.today()
        papers = [
            Paper(
                id="older-high-score",
                title="Enterprise Generative Recommendation with Semantic IDs",
                published=(today - dt.timedelta(days=1)).isoformat(),
                affiliations=["ByteDance"],
                abstract="Generative recommendation with semantic IDs and an online A/B test.",
            ),
            Paper(
                id="newer-low-score",
                title="Generative Retrieval",
                published=today.isoformat(),
                abstract="Generative retrieval validated in an online A/B test.",
            ),
        ]
        ranked = prepare_candidates(papers, self.config)
        self.assertEqual([item.id for item in ranked], ["newer-low-score", "older-high-score"])

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
