import type { Metadata } from "next";
import { StatusPanel } from "@/components/StatusPanel";
import { Verifier } from "@/components/verify/Verifier";

export const metadata: Metadata = {
  title: "Verify a message",
};

export default function VerifyPage() {
  return (
    <div className="page py-10 sm:py-14">
      <h1 className="text-2xl font-semibold sm:text-3xl">Verify a message</h1>
      <p className="mt-3 measure text-md text-muted">
        Add what you received. Satyapan checks it against official records and published fact checks, and shows each step as it runs.
      </p>
      <div className="mt-10 grid gap-10 lg:grid-cols-[minmax(0,1fr)_20rem] lg:items-start">
        <div className="min-w-0">
          <Verifier />
        </div>
        <aside className="lg:sticky lg:top-6" aria-label="System status">
          <StatusPanel />
        </aside>
      </div>
    </div>
  );
}
