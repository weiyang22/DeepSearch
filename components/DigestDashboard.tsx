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
  analysis_status: string;
  is_daily_pick: boolean;
};

type Payload = {
  generated_at: string;
  site: {
    title: string;
    subtitle: string;
    daily_limit: number;
    retention_days: number;
  };
  status: {
    analysis_enabled: boolean;
    source_errors: string[];
    discovered: number;
    candidates: number;
    daily_picks: number;
  };
  sources: string[];
  companies: string[];
  papers: Paper[];
};

type ViewMode = "today" | "all" | "paper" | "company" | "saved";
const MARKS_KEY = "deepsearch-saved-papers-v1";

export function DigestDashboard() {
  const [payload, setPayload] = useState<Payload | null>(null);
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<ViewMode>("today");
  const [tag, setTag] = useState("全部");
  const [company, setCompany] = useState("全部");
  const [saved, setSaved] = useState<string[]>([]);
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    try {
      setSaved(JSON.parse(window.localStorage.getItem(MARKS_KEY) || "[]"));
    } catch {
      setSaved([]);
    }
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

  const papers = payload?.papers || [];
  const tags = useMemo(() => unique(papers.flatMap((paper) => paper.tags)).slice(0, 18), [papers]);
  const companies = useMemo(() => unique(papers.map((paper) => paper.company).filter(Boolean)), [papers]);
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return papers.filter((paper) => {
      const haystack = [
        paper.title,
        paper.summary,
        paper.core_method,
        paper.company,
        paper.venue,
        ...(paper.authors || []),
        ...(paper.tags || []),
      ]
        .join(" ")
        .toLowerCase();
      const modeMatch =
        mode === "all" ||
        (mode === "today" && paper.is_daily_pick) ||
        (mode === "paper" && paper.content_type === "paper") ||
        (mode === "company" && paper.content_type === "company_report") ||
        (mode === "saved" && saved.includes(paper.id));
      return (
        modeMatch &&
        (!needle || haystack.includes(needle)) &&
        (tag === "全部" || paper.tags.includes(tag)) &&
        (company === "全部" || paper.company === company)
      );
    });
  }, [papers, query, mode, tag, company, saved]);

  const stats = useMemo(
    () => ({
      total: papers.length,
      reports: papers.filter((paper) => paper.content_type === "company_report").length,
      genrec: papers.filter((paper) => paper.tags.some((item) => ["GenRec", "Semantic ID", "Tokenization"].includes(item))).length,
      saved: saved.length,
    }),
    [papers, saved],
  );

  function toggleSaved(id: string) {
    setSaved((current) => (current.includes(id) ? current.filter((item) => item !== id) : [...current, id]));
  }

  if (loadError) {
    return (
      <main className="fatal-state">
        <span>DEEPSEARCH / DATA</span>
        <h1>论文数据暂时无法读取</h1>
        <p>每日采集可能仍在进行，请稍后刷新。</p>
      </main>
    );
  }

  if (!payload) {
    return (
      <main className="loading-state" role="status">
        <div className="loading-orbit" />
        <p>正在装载今日技术雷达…</p>
      </main>
    );
  }

  return (
    <main className="site-shell">
      <header className="site-header">
        <a className="brand" href="#top" aria-label="返回顶部">
          <span className="brand-mark">D/</span>
          <span>
            <strong>{payload.site.title}</strong>
            <small>DEEPSEARCH RESEARCH RADAR</small>
          </span>
        </a>
        <div className="header-meta">
          <span className="live-dot" />
          <span>每日 08:00 更新</span>
          <time>{formatGeneratedAt(payload.generated_at)}</time>
        </div>
      </header>

      <section className="hero" id="top">
        <div className="hero-copy">
          <p className="eyebrow">LLM × GENERATIVE RECOMMENDATION</p>
          <h1>把前沿论文，<br />压缩成可行动的判断。</h1>
          <p className="hero-lead">{payload.site.subtitle}。追踪研究论文，也追踪 Kimi、DeepSeek、MiniMax 与智谱的官方技术发布。</p>
          <div className="hero-actions">
            <button className="primary-action" onClick={() => setMode("today")}>阅读今日 4 篇</button>
            <button className="secondary-action" onClick={() => setMode("company")}>查看公司报告</button>
          </div>
        </div>
        <div className="radar-card" aria-label="今日雷达统计">
          <div className="radar-grid" />
          <div className="radar-sweep" />
          <div className="radar-core">
            <strong>{payload.status.daily_picks}</strong>
            <span>DAILY PICKS</span>
          </div>
          <span className="signal signal-a">LLM</span>
          <span className="signal signal-b">SID</span>
          <span className="signal signal-c">GR</span>
        </div>
      </section>

      <section className="metrics" aria-label="归档统计">
        <Metric value={stats.total} label={`${payload.site.retention_days} 天归档`} />
        <Metric value={stats.reports} label="官方技术发布" />
        <Metric value={stats.genrec} label="GenRec / SID" />
        <Metric value={stats.saved} label="我的收藏" />
      </section>

      {!payload.status.analysis_enabled && (
        <div className="system-note">
          <span>AI 分析等待激活</span>
          <p>当前卡片使用原始摘要和保守说明；配置 DeepSeek API 后，将自动生成完整中文扩展分析。</p>
        </div>
      )}

      <section className="explorer" id="archive">
        <div className="explorer-head">
          <div>
            <p className="section-index">01 / RESEARCH FEED</p>
            <h2>技术情报流</h2>
          </div>
          <label className="search-box">
            <span>⌕</span>
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索论文、作者、公司或技术路线" />
          </label>
        </div>

        <div className="view-tabs" role="tablist" aria-label="内容范围">
          <ViewTab active={mode === "today"} onClick={() => setMode("today")} label="今日精选" count={papers.filter((paper) => paper.is_daily_pick).length} />
          <ViewTab active={mode === "all"} onClick={() => setMode("all")} label="全部归档" count={papers.length} />
          <ViewTab active={mode === "paper"} onClick={() => setMode("paper")} label="学术论文" />
          <ViewTab active={mode === "company"} onClick={() => setMode("company")} label="公司报告" />
          <ViewTab active={mode === "saved"} onClick={() => setMode("saved")} label="已收藏" count={saved.length} />
        </div>

        <div className="filter-row">
          <div className="tag-cloud" aria-label="主题标签">
            <button className={tag === "全部" ? "active" : ""} onClick={() => setTag("全部")}>全部主题</button>
            {tags.map((item) => (
              <button key={item} className={tag === item ? "active" : ""} onClick={() => setTag(item)}>{item}</button>
            ))}
          </div>
          <label className="company-filter">
            <span>公司</span>
            <select value={company} onChange={(event) => setCompany(event.target.value)}>
              <option>全部</option>
              {companies.map((item) => <option key={item}>{item}</option>)}
            </select>
          </label>
        </div>

        <div className="result-line">
          <span>{viewLabel(mode)}</span>
          <strong>{filtered.length} 条结果</strong>
        </div>

        <div className="paper-list">
          {filtered.map((paper, index) => (
            <PaperCard key={paper.id} paper={paper} index={index + 1} saved={saved.includes(paper.id)} onSave={() => toggleSaved(paper.id)} />
          ))}
          {!filtered.length && <div className="empty-result">没有符合当前条件的内容，试试清除筛选或切换归档范围。</div>}
        </div>
      </section>

      <footer>
        <div><strong>LLM&GR</strong><span>DeepSearch</span></div>
        <p>数据来自公开学术索引与公司官方发布。AI 生成内容仅用于研究筛选，请以原文为准。</p>
        <a href="#top">返回顶部 ↑</a>
      </footer>
    </main>
  );
}

function PaperCard({ paper, index, saved, onSave }: { paper: Paper; index: number; saved: boolean; onSave: () => void }) {
  return (
    <article className={`paper-card ${paper.is_daily_pick ? "daily" : ""}`}>
      <div className="card-rail">
        <span>{String(index).padStart(2, "0")}</span>
        <div />
      </div>
      <div className="card-body">
        <div className="card-kicker">
          <span className={`type-badge ${paper.content_type}`}>{paper.content_type === "company_report" ? "官方技术发布" : "研究论文"}</span>
          {paper.company && <span className="company-badge">{paper.company}</span>}
          <span>{paper.venue || paper.source}</span>
          <time>{formatPaperDate(paper.published)}</time>
          <span>{evidenceLabel(paper.evidence_basis)}</span>
        </div>
        <div className="title-row">
          <div>
            <h3>{paper.title}</h3>
            <p className="authors">{compact(paper.authors, 7) || "作者信息待补充"}</p>
          </div>
          <button className={`save-button ${saved ? "saved" : ""}`} onClick={onSave} aria-label={saved ? "取消收藏" : "收藏论文"} title={saved ? "取消收藏" : "收藏"}>{saved ? "★" : "☆"}</button>
        </div>
        <p className="takeaway"><span>一句话结论</span>{paper.one_line_takeaway}</p>
        <p className="summary">{paper.summary}</p>
        <div className="tag-row">{paper.tags.map((item) => <span key={item}>{item}</span>)}</div>

        <details className="analysis-panel">
          <summary>展开完整分析 <span>＋</span></summary>
          <div className="analysis-grid">
            <AnalysisBlock title="核心方法" text={paper.core_method} />
            <AnalysisBlock title="为什么值得读" text={paper.why_it_matters} accent />
            <AnalysisList title="创新点" items={paper.innovation_points} />
            <AnalysisList title="实验结果" items={paper.experiment_results} />
            <AnalysisList title="局限与边界" items={paper.limitations} />
            <AnalysisBlock title="实践价值" text={paper.practical_value} />
          </div>
        </details>

        <div className="card-links">
          {paper.url && <a href={paper.url} target="_blank" rel="noreferrer">查看原文 ↗</a>}
          {paper.pdf_url && <a href={paper.pdf_url} target="_blank" rel="noreferrer">PDF ↗</a>}
          <span>相关度 {paper.score}</span>
        </div>
      </div>
    </article>
  );
}

function Metric({ value, label }: { value: number; label: string }) {
  return <div className="metric"><strong>{String(value).padStart(2, "0")}</strong><span>{label}</span></div>;
}

function ViewTab({ active, onClick, label, count }: { active: boolean; onClick: () => void; label: string; count?: number }) {
  return <button role="tab" aria-selected={active} className={active ? "active" : ""} onClick={onClick}>{label}{typeof count === "number" && <span>{count}</span>}</button>;
}

function AnalysisBlock({ title, text, accent = false }: { title: string; text: string; accent?: boolean }) {
  return <section className={accent ? "analysis-block accent" : "analysis-block"}><h4>{title}</h4><p>{text || "暂无明确证据。"}</p></section>;
}

function AnalysisList({ title, items }: { title: string; items: string[] }) {
  return <section className="analysis-block"><h4>{title}</h4><ul>{(items || []).map((item, index) => <li key={`${title}-${index}`}>{item}</li>)}</ul></section>;
}

function compact(values: string[] = [], limit: number) {
  if (values.length <= limit) return values.join(" · ");
  return `${values.slice(0, limit).join(" · ")} 等 ${values.length} 位作者`;
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

function evidenceLabel(value: Paper["evidence_basis"]) {
  return value === "official_release" ? "官方材料" : value === "abstract" ? "摘要分析" : "元数据分析";
}

function viewLabel(mode: ViewMode) {
  return { today: "TODAY / 今日精选", all: "ARCHIVE / 全部归档", paper: "PAPERS / 学术论文", company: "REPORTS / 公司报告", saved: "SAVED / 已收藏" }[mode];
}
