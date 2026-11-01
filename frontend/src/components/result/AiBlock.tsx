import { aiExplanationLabel, aiStepLabel } from "@/lib/labels";
import type { AiInfo } from "@/lib/types";

export function AiBlock({ ai }: { ai: AiInfo }) {
  const problems = ai.problems ?? [];
  return (
    <section aria-labelledby="ai-heading">
      <h2 id="ai-heading" className="text-xl font-semibold">
        How AI was used
      </h2>
      <p className="mt-1 measure text-sm text-muted">
        The AI model can extract claims, compare evidence and write the explanation. It never sets the verdict.
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
      <div className="mt-4 text-sm">
        <h3 className="font-sans text-base font-semibold">AI outputs rejected by code checks</h3>
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
