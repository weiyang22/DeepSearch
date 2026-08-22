# DeepSearch · LLM&GR

追踪大模型基座技术、生成式推荐、Generative Retrieval 与 Semantic ID 论文，同时监测 Kimi、DeepSeek、MiniMax、智谱官方渠道中的新技术报告。

## 功能

- arXiv、DBLP、OpenAlex、Semantic Scholar 多源发现与降级
- LLM 仅收录企业参与或企业官方发布的预训练、基模架构、训练数据、扩展规律、对齐/后训练及训练推理系统论文
- GenRec/SID 只收录明确报告 A/B 测试或线上受控实验的论文
- DeepSeek `deepseek-v4-flash` 中文扩展分析
- 每日数量不设硬上限，按发布时间窗口与质量分动态入选
- 365 天滚动归档、搜索、标签、公司筛选和本地收藏
- 使用 DeepSeek 回补并维护完整 365 天归档的中文扩展分析；已有结果按签名复用，避免重复调用
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
