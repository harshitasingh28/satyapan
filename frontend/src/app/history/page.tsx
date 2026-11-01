import type { Metadata } from "next";
import { HistoryList } from "@/components/HistoryList";

export const metadata: Metadata = {
  title: "History",
};

export default function HistoryPage() {
  return (
    <div className="page py-10 sm:py-14">
      <h1 className="text-2xl font-semibold sm:text-3xl">History</h1>
      <div className="mt-6">
        <HistoryList />
      </div>
    </div>
  );
}
