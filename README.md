# DeepSearch · LLM&GR

每日追踪大模型、生成式推荐、Generative Retrieval 与 Semantic ID 论文，同时监测 Kimi、DeepSeek、MiniMax、智谱官方 GitHub 中的新技术报告。

## 功能

- arXiv、DBLP、OpenAlex、Semantic Scholar 多源发现与降级
- DeepSeek `deepseek-v4-flash` 中文扩展分析
- 每日 4 篇，兼顾公司技术报告和 GenRec/SID 论文
- 90 天滚动归档、搜索、标签、公司筛选和本地收藏
- GitHub Actions 每天北京时间 08:00 自动更新
- API 失败时保留原始摘要并继续发布

## 本地运行

```bash
cp .env.example .env.local
set -a && source .env.local && set +a
uv run --python 3.11 python -m deepsearch.main
npm install
npm run dev
```

静态 GitHub Pages 构建：

```bash
npm run build:pages
```

## GitHub Secrets

- `DEEPSEEK_API_KEY`：必填，生成中文扩展分析
- `SEMANTIC_SCHOLAR_API_KEY`：可选，提高 Semantic Scholar 稳定性

不要把 API Key 写进配置文件或提交到仓库。
