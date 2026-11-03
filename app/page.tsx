import type { Metadata } from "next";
import { DigestDashboard } from "@/components/DigestDashboard";

export const metadata: Metadata = {
  title: "deepsearch",
  description: "SOTA 论文追踪：大模型基座、生成式推荐与具身智能。",
};

export default function Home() {
  return <DigestDashboard />;
}
