import { aiExplanationLabel, aiStepLabel } from "@/lib/labels";
import type { AiInfo, AiPair, AiPlan } from "@/lib/types";
import { Chip, SafeLink } from "../primitives";

const LANGUAGES: Record<string, string> = { en: "English", hi: "Hindi", te: "Telugu", mixed: "Mixed", other: "Other" };

function humanType(value: string | null | undefined): string {
  if (!value) return "Not classified";
  const text = value.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function planStatus(plan: AiPlan): string {
  if (plan.status === "used") return "Ran";
  if (plan.status === "no_claim") return "Not needed, no text claim";
  return aiStepLabel(plan.status);
}

function PlanSection({ plan }: { plan: AiPlan }) {
  const decisions = plan.decisions ?? [];
  return (
    <div className="mt-4">
      <h3 className="font-sans text-base font-semibold">1. Plan: which checks to run</h3>
      <p className="mt-1 text-sm text-muted">
        The AI chooses optional checks and writes search queries. Code keeps the safety checks, rejects any query that adds a
        number or a link, and never treats a search result as evidence without its own checks.
      </p>
      <dl className="mt-2 grid gap-x-4 gap-y-1 text-sm sm:grid-cols-[max-content_minmax(0,1fr)]">
        <dt className="text-muted">AI planner</dt>
        <dd>{planStatus(plan)}</dd>
        {plan.status === "used" && (
          <>
            <dt className="text-muted">Claim type</dt>
            <dd>{humanType(plan.claim_type)}</dd>
            <dt className="text-muted">Language</dt>
            <dd>{LANGUAGES[plan.language ?? ""] ?? plan.language ?? "Unknown"}</dd>
          </>
        )}
      </dl>
      {decisions.length > 0 && (
        <div className="mt-2 overflow-x-auto">
          <table className="w-full min-w-[32rem] text-left text-sm">
            <caption className="sr-only">Checks chosen for this message</caption>
            <thead>
              <tr className="border-b border-rule text-muted">
                <th scope="col" className="py-1.5 pr-3 font-medium">Check</th>
                <th scope="col" className="py-1.5 pr-3 font-medium">Ran</th>
                <th scope="col" className="py-1.5 pr-3 font-medium">Decided by</th>
                <th scope="col" className="py-1.5 font-medium">Why</th>
              </tr>
            </thead>
            <tbody>
              {decisions.map((d, i) => (
                <tr key={i} className="border-b border-rule align-top last:border-0">
                  <td className="py-1.5 pr-3">{d.check}</td>
                  <td className="py-1.5 pr-3">{d.run ? "Yes" : "No"}</td>
                  <td className="py-1.5 pr-3">
                    <Chip tone={d.decided_by === "ai" ? "info" : "neutral"}>{d.decided_by === "ai" ? "AI" : "Code rule"}</Chip>
                  </td>
                  <td className="py-1.5 break-anywhere">
                    {d.why}
                    {d.queries && d.queries.length > 0 && (
                      <ul className="mt-1 list-disc pl-5">
                        {d.queries.map((q, j) => (
                          <li key={j} className="break-anywhere">
                            Search: <q>{q}</q>
                          </li>
                        ))}
                      </ul>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function PairItem({ pair }: { pair: AiPair }) {
  const kind = pair.type === "official_release" ? "Official release" : "Published fact-check";
  return (
    <li className="rounded-md border border-rule p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="tabular font-semibold">{pair.candidate}</span>
        <span className="text-muted">{kind}</span>
        {pair.verified ? (
          <Chip tone="good">Quotes verified in the source</Chip>
        ) : (
          <Chip tone="warn">Rejected by code</Chip>
        )}
      </div>
      {pair.text && <p className="mt-1 break-anywhere text-sm">{pair.text}</p>}
      <dl className="mt-1 grid gap-x-3 gap-y-0.5 text-sm sm:grid-cols-[max-content_minmax(0,1fr)]">
        {pair.verified && (
          <>
            <dt className="text-muted">AI judgement</dt>
            <dd>
              {humanType(pair.relation)}
              {pair.same_subject === false ? ", different subject" : ""}
            </dd>
            {pair.evidence_quote && (
              <>
                <dt className="text-muted">Quoted from source</dt>
                <dd className="break-anywhere">
                  <q>{pair.evidence_quote}</q>
                </dd>
              </>
            )}
          </>
        )}
        {!pair.verified && pair.problem && (
          <>
            <dt className="text-muted">Why rejected</dt>
            <dd className="break-anywhere">{pair.problem}</dd>
          </>
        )}
        {typeof pair.cosine === "number" && (
          <>
            <dt className="text-muted">Embedding similarity</dt>
            <dd className="tabular">{pair.cosine.toFixed(2)}</dd>
          </>
        )}
        {pair.source_url && (
          <>
            <dt className="text-muted">Source</dt>
            <dd>
              <SafeLink url={pair.source_url} />
            </dd>
          </>
        )}
      </dl>
    </li>
  );
}

export function AiBlock({ ai }: { ai: AiInfo }) {
  const problems = ai.problems ?? [];
  const pairs = ai.pairs ?? [];
  return (
    <section aria-labelledby="ai-heading">
      <h2 id="ai-heading" className="text-xl font-semibold">
        How the AI reasoned
      </h2>
      <p className="mt-1 measure text-sm text-muted">
        The AI model plans the checks, extracts claims, compares evidence and writes the explanation. Code checks every quote
        it produces, and code alone sets the verdict.
      </p>
      <dl className="mt-3 grid gap-x-4 gap-y-1.5 text-sm sm:grid-cols-[max-content_minmax(0,1fr)]">
        <dt className="text-muted">Chat model</dt>
        <dd className="break-anywhere">{ai.chat_model ?? "None"}</dd>
        <dt className="text-muted">Embedding model</dt>
        <dd className="break-anywhere">{ai.embedding_model ?? "None"}</dd>
        <dt className="text-muted">Claim extraction</dt>
        <dd>{aiStepLabel(ai.extraction)}</dd>
        <dt className="text-muted">Evidence comparison</dt>
        <dd>{aiStepLabel(ai.comparison)}</dd>
        <dt className="text-muted">Explanation</dt>
        <dd>{aiExplanationLabel(ai.explanation)}</dd>
      </dl>

      {ai.plan && <PlanSection plan={ai.plan} />}

      <div className="mt-4">
        <h3 className="font-sans text-base font-semibold">2. Comparison: claim against each candidate source</h3>
        {pairs.length === 0 ? (
          <p className="mt-1 text-sm text-muted">No official release or fact-check was close enough to compare.</p>
        ) : (
          <ul className="mt-2 space-y-2">
            {pairs.map((p, i) => (
              <PairItem key={`${p.candidate}-${i}`} pair={p} />
            ))}
          </ul>
        )}
      </div>

      <div className="mt-4 text-sm">
        <h3 className="font-sans text-base font-semibold">3. AI outputs rejected by code checks</h3>
        {problems.length === 0 ? (
          <p className="mt-1 text-muted">None.</p>
        ) : (
          <ul className="mt-1 list-disc space-y-1 pl-5">
            {problems.map((p, i) => (
              <li key={i} className="break-anywhere">
                {p}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
