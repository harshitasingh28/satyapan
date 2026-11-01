import { formatMs } from "@/lib/format";
import { toolStatusInfo } from "@/lib/labels";
import type { ToolRun } from "@/lib/types";
import { Chip } from "../primitives";

export function ToolRunsTable({ runs }: { runs: ToolRun[] }) {
  return (
    <section aria-labelledby="tools-heading">
      <h2 id="tools-heading" className="text-xl font-semibold">
        Tool runs
      </h2>
      <p className="mt-1 measure text-sm text-muted">Every tool the server called for this investigation, with its result.</p>
      {runs.length === 0 ? (
        <p className="mt-3 text-sm">No tools ran.</p>
      ) : (
        <div className="mt-3 overflow-x-auto" role="region" aria-label="Tool runs table" tabIndex={0}>
          <table className="data-table min-w-[36rem]">
            <thead>
              <tr>
                <th scope="col">Tool</th>
                <th scope="col">Checked</th>
                <th scope="col">Status</th>
                <th scope="col" className="text-right">
                  Time
                </th>
                <th scope="col">Detail</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run, i) => {
                const info = toolStatusInfo(run.status);
                return (
                  <tr key={`${run.tool}-${i}`}>
                    <td className="font-medium whitespace-nowrap">{run.tool}</td>
                    <td className="max-w-[16rem] break-anywhere">{run.target}</td>
                    <td>
                      <Chip tone={info.tone}>{info.label}</Chip>
                    </td>
                    <td className="tabular text-right whitespace-nowrap">{formatMs(run.ms)}</td>
                    <td className="max-w-[18rem] break-anywhere text-muted">{run.detail}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
