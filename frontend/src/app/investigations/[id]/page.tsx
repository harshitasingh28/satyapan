import type { Metadata } from "next";
import { InvestigationView } from "@/components/InvestigationView";

export const metadata: Metadata = {
  title: "Investigation",
  robots: { index: false, follow: false },
};

export default async function InvestigationPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <InvestigationView id={id} />;
}
