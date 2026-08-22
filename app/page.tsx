import type { Metadata } from "next";
import { DigestDashboard } from "@/components/DigestDashboard";

export const metadata: Metadata = {
  title: "LLM&GR · DeepSearch",
  description: "每日追踪大模型、生成式推荐与 Semantic ID 论文和官方技术报告。",
};

export default function Home() {
  return <DigestDashboard />;
}
