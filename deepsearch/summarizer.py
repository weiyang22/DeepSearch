from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request

from .config import Config
from .models import Paper

PROMPT_VERSION = "deepsearch-analysis-v1"
ANALYSIS_FIELDS = (
    "summary",
    "one_line_takeaway",
    "core_method",
    "innovation_points",
    "experiment_results",
    "limitations",
    "practical_value",
    "why_it_matters",
    "tags",
    "evidence_basis",
    "analysis_status",
    "analysis_signature",
)


def analyze_papers(papers: list[Paper], previous_by_id: dict[str, Paper], config: Config) -> None:
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    for paper in papers:
        signature = analysis_signature(paper, config)
        cached = previous_by_id.get(paper.id)
        if cached and cached.analysis_signature == signature and cached.summary:
            _copy_analysis(cached, paper)
            paper.analysis_status = "cached"
            continue
        result: dict[str, object] = {}
        if api_key:
            try:
                result = _call_deepseek(paper, config, api_key)
            except Exception:
                result = {}
        _apply_result(paper, result)
        paper.analysis_signature = signature


def analysis_signature(paper: Paper, config: Config) -> str:
    payload = {
        "prompt": PROMPT_VERSION,
        "model": config.deepseek_model,
        "id": paper.id,
        "updated": paper.updated,
        "title": paper.title,
        "abstract": paper.abstract,
        "content_type": paper.content_type,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def _call_deepseek(paper: Paper, config: Config, api_key: str) -> dict[str, object]:
    evidence = "官方技术发布" if paper.content_type == "company_report" else "标题、摘要和学术元数据"
    system_prompt = (
        "你是关注大模型、生成式推荐和语义ID的资深研究分析师。"
        "请只基于给定材料分析，不要补造实验数据。输出严格JSON，不要输出解释或Markdown。"
        "description要比普通论文摘要更完整，说明研究问题、技术路线和结果。"
        "JSON字段：summary（120-220字中文扩展摘要）、one_line_takeaway（一句话结论）、"
        "core_method（核心方法）、innovation_points（2-4项）、experiment_results（1-3项，没有数据要明确说明）、"
        "limitations（1-3项）、practical_value（实践价值）、why_it_matters（为什么值得读）、"
        "tags（2-6个标签）。"
    )
    user_prompt = (
        f"内容类型：{paper.content_type}\n公司：{paper.company or '无'}\n证据来源：{evidence}\n"
        f"标题：{paper.title}\n作者：{', '.join(paper.authors)}\n会议/来源：{paper.venue or paper.source}\n"
        f"摘要或官方介绍：{paper.abstract or '没有摘要，请保守分析标题和来源。'}"
    )
    payload = {
        "model": config.deepseek_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
        "max_tokens": 1400,
        "temperature": 0.2,
    }
    request = urllib.request.Request(
        config.deepseek_base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"DeepSeek API error {exc.code}") from exc
    content = data["choices"][0]["message"]["content"]
    return json.loads(content)


def _apply_result(paper: Paper, result: dict[str, object]) -> None:
    abstract_excerpt = (paper.abstract or "暂无可用摘要").strip()
    if len(abstract_excerpt) > 520:
        abstract_excerpt = abstract_excerpt[:517].rstrip() + "..."
    paper.summary = str(result.get("summary") or abstract_excerpt)
    paper.one_line_takeaway = str(
        result.get("one_line_takeaway")
        or ("这是来自官方渠道的最新技术发布，值得结合完整报告进一步阅读。" if paper.content_type == "company_report" else "该工作与大模型或生成式推荐方向相关，建议结合原文确认技术细节。")
    )
    paper.core_method = str(result.get("core_method") or "尚未配置 DeepSeek API，核心方法需结合原文进一步提取。")
    paper.innovation_points = _list(result.get("innovation_points"), ["待从完整论文或技术报告中进一步提取。"])
    paper.experiment_results = _list(result.get("experiment_results"), ["当前元数据未提供足够的实验结果细节。"])
    paper.limitations = _list(result.get("limitations"), ["当前分析仅基于公开摘要或官方介绍，结论需以原文为准。"])
    paper.practical_value = str(result.get("practical_value") or "可作为 LLM 与生成式推荐技术跟踪的候选阅读材料。")
    paper.why_it_matters = str(result.get("why_it_matters") or "与当前关注的 LLM、GenRec 或 Semantic ID 技术路线存在直接关联。")
    if isinstance(result.get("tags"), list):
        paper.tags = _unique([*paper.tags, *[str(item) for item in result["tags"]]])[:6]
    paper.evidence_basis = "official_release" if paper.content_type == "company_report" else "abstract"
    paper.analysis_status = "complete" if result else "fallback"


def _copy_analysis(source: Paper, target: Paper) -> None:
    for name in ANALYSIS_FIELDS:
        value = getattr(source, name)
        setattr(target, name, list(value) if isinstance(value, list) else value)


def _list(value: object, fallback: list[str]) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return fallback
    cleaned = _unique(str(item).strip() for item in value if str(item).strip())
    return cleaned or fallback


def _unique(values) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
