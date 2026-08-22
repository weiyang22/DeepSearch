import type { Metadata } from "next";
import { DigestDashboard } from "@/components/DigestDashboard";

export const metadata: Metadata = {
  title: "LLM&GR · DeepSearch",
  description: "追踪大模型基座技术与企业优先的生成式推荐论文。",
};

export default function Home() {
  return <DigestDashboard />;
}
