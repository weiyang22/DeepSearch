"use client";

import { useEffect, useMemo, useState } from "react";

type Paper = {
  id: string;
  title: string;
  authors: string[];
  affiliations: string[];
  published: string;
  abstract: string;
  url: string;
  pdf_url: string;
  source: string;
  content_type: "paper" | "company_report";
  company: string;
  venue: string;
  tags: string[];
  score: number;
  summary: string;
  one_line_takeaway: string;
  core_method: string;
  innovation_points: string[];
  experiment_results: string[];
  limitations: string[];
  practical_value: string;
  why_it_matters: string;
  evidence_basis: "abstract" | "metadata" | "official_release";
  is_daily_pick: boolean;
};

type Payload = {
  generated_at: string;
  site: {
    title: string;
    subtitle: string;
    daily_limit: number;
    daily_window_days?: number;
    retention_days: number;
  };
  status: {
    analysis_enabled: boolean;
    daily_picks: number;
  };
  papers: Paper[];
};

type ViewMode = "today" | "llm" | "genrec" | "company" | "all" | "saved";
const MARKS_KEY = "deepsearch-saved-papers-v1";
const GENREC_TAGS = ["GenRec", "Semantic ID", "Tokenization"];
const LLM_TAGS = ["LLM 基模", "预训练", "后训练", "MoE", "训练系统", "推理系统"];

export function DigestDashboard() {
  const [payload, setPayload] = useState<Payload | null>(null);
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<ViewMode>("today");
  const [tag, setTag] = useState("全部");
  const [saved, setSaved] = useState<string[]>([]);
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    queueMicrotask(() => {
      try {
        setSaved(JSON.parse(window.localStorage.getItem(MARKS_KEY) || "[]"));
      } catch {
        setSaved([]);
      }
    });
    fetch("./papers.json")
      .then((response) => {
        if (!response.ok) throw new Error("data unavailable");
        return response.json();
      })
      .then(setPayload)
      .catch(() => setLoadError(true));
  }, []);

  useEffect(() => {
    window.localStorage.setItem(MARKS_KEY, JSON.stringify(saved));
  }, [saved]);

  const papers = useMemo(
    () => [...(payload?.papers || [])].sort((a, b) => paperTimestamp(b.published) - paperTimestamp(a.published) || b.score - a.score),
    [payload],
  );
  const tags = useMemo(() => unique(papers.flatMap((paper) => paper.tags)).slice(0, 16), [papers]);
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return papers.filter((paper) => {
      const haystack = [paper.title, paper.summary, paper.core_method, paper.company, paper.venue, ...(paper.authors || []), ...(paper.tags || [])]
        .join(" ")
        .toLowerCase();
      const modeMatch =
        mode === "all" ||
        (mode === "today" && paper.is_daily_pick) ||
        (mode === "llm" && paper.tags.includes("企业论文") && paper.tags.some((item) => LLM_TAGS.includes(item))) ||
        (mode === "genrec" && paper.tags.some((item) => GENREC_TAGS.includes(item))) ||
        (mode === "company" && (paper.content_type === "company_report" || paper.tags.includes("企业论文"))) ||
        (mode === "saved" && saved.includes(paper.id));
      return modeMatch && (!needle || haystack.includes(needle)) && (tag === "全部" || paper.tags.includes(tag));
    });
  }, [papers, query, mode, tag, saved]);

  function toggleSaved(id: string) {
    setSaved((current) => (current.includes(id) ? current.filter((item) => item !== id) : [...current, id]));
  }

  if (loadError) {
    return <main className="center-state"><h1>数据暂时无法读取</h1><p>每日采集可能仍在进行，请稍后刷新。</p></main>;
  }

  if (!payload) {
    return <main className="center-state" role="status"><p>正在加载 LLM&GR…</p></main>;
  }

  const todayCount = papers.filter((paper) => paper.is_daily_pick).length;

  return (
    <main className="site-shell" id="top">
      <header className="site-header">
        <a className="brand" href="#top">{payload.site.title}<small>DeepSearch</small></a>
        <p>每天 08:00 更新 · {formatGeneratedAt(payload.generated_at)}</p>
      </header>

      <section className="intro">
        <p className="eyebrow">LLM FOUNDATION MODELS × GENERATIVE RECOMMENDATION</p>
        <h1>大模型基座技术与生成式推荐论文追踪</h1>
        <p className="intro-copy">
          LLM 仅关注企业参与或企业官方发布的预训练、基模架构、训练数据、对齐与后训练等技术内容；不收录普通应用层或纯学术论文。
          重点跟踪中美主流模型机构及 GPT、Claude、Gemini、Llama、Grok、DeepSeek、Kimi、MiniMax、GLM、Qwen、MiMo 等模型家族。
          GenRec 聚焦生成式推荐、生成式检索与 Semantic ID，
          并且只收录明确报告 A/B 测试或线上受控实验的工作。
        </p>
        <div className="intro-meta">
          <span>今日收录 <strong>{todayCount}</strong> 篇，不设固定数量</span>
          <span>滚动保留 {payload.site.retention_days} 天</span>
          <span>共 {papers.length} 篇</span>
        </div>
      </section>

      {!payload.status.analysis_enabled && (
        <p className="notice">尚未配置 AI Key，当前显示原始摘要与保守分析；配置后会自动补全中文深度解读。</p>
      )}

      <section className="feed" aria-label="论文列表">
        <div className="toolbar">
          <nav className="view-tabs" aria-label="内容范围">
            <ViewTab active={mode === "today"} onClick={() => setMode("today")} label="今日" count={todayCount} />
            <ViewTab active={mode === "llm"} onClick={() => setMode("llm")} label="LLM 基模" />
            <ViewTab active={mode === "genrec"} onClick={() => setMode("genrec")} label="GenRec" />
            <ViewTab active={mode === "company"} onClick={() => setMode("company")} label="企业 / 官方" />
            <ViewTab active={mode === "all"} onClick={() => setMode("all")} label="全部" />
            <ViewTab active={mode === "saved"} onClick={() => setMode("saved")} label="收藏" count={saved.length} />
          </nav>
          <label className="search-box">
            <span>搜索</span>
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="标题、作者、公司或技术" />
          </label>
        </div>

        <div className="tag-cloud" aria-label="主题标签">
          <button className={tag === "全部" ? "active" : ""} onClick={() => setTag("全部")}>全部标签</button>
          {tags.map((item) => <button key={item} className={tag === item ? "active" : ""} onClick={() => setTag(item)}>{item}</button>)}
        </div>

        <div className="result-line"><span>{viewLabel(mode)}</span><span>{filtered.length} 篇</span></div>

        <div className="paper-list">
          {filtered.map((paper) => (
            <PaperCard key={paper.id} paper={paper} saved={saved.includes(paper.id)} onSave={() => toggleSaved(paper.id)} />
          ))}
          {!filtered.length && <div className="empty-result">当前筛选下没有内容。</div>}
        </div>
      </section>

      <footer>
        <p>数据来自公开学术索引及公司官方发布。AI 分析用于研究筛选，请以原文为准。</p>
        <a href="#top">返回顶部</a>
      </footer>
    </main>
  );
}

function PaperCard({ paper, saved, onSave }: { paper: Paper; saved: boolean; onSave: () => void }) {
  return (
    <article className="paper-card">
      <div className="card-kicker">
        <span className="type-badge">{paperTypeLabel(paper)}</span>
        {paper.company && <span>{paper.company}</span>}
        <span>{paper.venue || paper.source}</span>
        <time>{formatPaperDate(paper.published)}</time>
      </div>
      <div className="title-row">
        <div><h2>{paper.title}</h2><p className="authors">{compact(paper.authors, 6) || "作者信息待补充"}</p></div>
        <button className={`save-button ${saved ? "saved" : ""}`} onClick={onSave} aria-label={saved ? "取消收藏" : "收藏论文"}>{saved ? "已收藏" : "收藏"}</button>
      </div>
      <p className="takeaway">{paper.one_line_takeaway}</p>
      <p className="summary">{paper.summary}</p>
      <div className="tag-row" aria-label="论文标签">
        {paper.tags.map((item) => (
          <span className={`paper-tag ${tagTone(item, paper)}`} key={item}><b>#</b>{item}</span>
        ))}
      </div>

      <details className="analysis-panel">
        <summary>详细分析 <span>＋</span></summary>
        <div className="analysis-grid">
          <AnalysisBlock title="核心方法" text={paper.core_method} />
          <AnalysisBlock title="为什么值得读" text={paper.why_it_matters} />
          <AnalysisList title="创新点" items={paper.innovation_points} />
          <AnalysisList title="实验结果" items={paper.experiment_results} />
          <AnalysisList title="局限" items={paper.limitations} />
          <AnalysisBlock title="实践价值" text={paper.practical_value} />
        </div>
      </details>

      <div className="card-links">
        {paper.url && <a href={paper.url} target="_blank" rel="noreferrer">原文 ↗</a>}
        {paper.pdf_url && <a href={paper.pdf_url} target="_blank" rel="noreferrer">PDF ↗</a>}
        <span>相关度 {paper.score}</span>
      </div>
    </article>
  );
}

function ViewTab({ active, onClick, label, count }: { active: boolean; onClick: () => void; label: string; count?: number }) {
  return <button className={active ? "active" : ""} onClick={onClick}>{label}{typeof count === "number" && <span>{count}</span>}</button>;
}

function AnalysisBlock({ title, text }: { title: string; text: string }) {
  return <section className="analysis-block"><h3>{title}</h3><p>{text || "暂无明确证据。"}</p></section>;
}

function AnalysisList({ title, items }: { title: string; items: string[] }) {
  return <section className="analysis-block"><h3>{title}</h3><ul>{(items || []).map((item, index) => <li key={`${title}-${index}`}>{item}</li>)}</ul></section>;
}

function compact(values: string[] = [], limit: number) {
  return values.length <= limit ? values.join(" · ") : `${values.slice(0, limit).join(" · ")} 等 ${values.length} 位作者`;
}

function paperTimestamp(value: string) {
  const timestamp = Date.parse(value);
  return Number.isNaN(timestamp) ? 0 : timestamp;
}

function paperTypeLabel(paper: Paper) {
  if (paper.content_type === "company_report") return "官方技术报告";
  if (paper.tags.includes("企业论文")) return "企业研究论文";
  return "研究论文";
}

function tagTone(tag: string, paper: Paper) {
  if (tag === paper.company) return "paper-tag--company";
  if (["企业论文", "官方技术报告", "A/B 实验"].includes(tag)) return "paper-tag--evidence";
  if (["LLM 基模", "GenRec", "Semantic ID"].includes(tag)) return "paper-tag--primary";
  return "paper-tag--topic";
}

function unique(values: string[]) {
  return [...new Set(values)];
}

function formatGeneratedAt(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(date);
}

function formatPaperDate(value: string) {
  const match = String(value || "").match(/\d{4}-\d{2}-\d{2}/);
  return match ? match[0].replaceAll("-", ".") : value.slice(0, 4) || "日期未知";
}

function viewLabel(mode: ViewMode) {
  return { today: "今日收录", llm: "LLM 基模技术", genrec: "GenRec / Semantic ID", company: "企业与官方发布", all: "全部归档", saved: "我的收藏" }[mode];
}
