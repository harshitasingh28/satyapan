"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, getStatus } from "./api";
import type { Status } from "./types";

export type StatusState =
  | { kind: "loading" }
  | { kind: "ok"; status: Status }
  | { kind: "error"; message: string };

// One request is shared by every component on the page and kept across
// client-side navigation. A failed request is not cached.
let pending: Promise<Status> | null = null;
let cached: Status | null = null;

function load(force: boolean): Promise<Status> {
  if (cached && !force) return Promise.resolve(cached);
  if (pending && !force) return pending;
  pending = getStatus()
    .then((status) => {
      cached = status;
      return status;
    })
    .finally(() => {
      pending = null;
    });
  return pending;
}

export function useStatus(): StatusState & { reload: () => void } {
  const [state, setState] = useState<StatusState>(() => (cached ? { kind: "ok", status: cached } : { kind: "loading" }));

  const run = useCallback((force: boolean) => {
    if (force) setState({ kind: "loading" });
    load(force).then(
      (status) => setState({ kind: "ok", status }),
      (error: unknown) =>
        setState({
          kind: "error",
          message: error instanceof ApiError ? error.message : "The system status could not be read.",
        }),
    );
  }, []);

  useEffect(() => {
    run(false);
  }, [run]);

  const reload = useCallback(() => run(true), [run]);
  return { ...state, reload };
}

/** Test helper: forget the cached status. */
export function resetStatusCache(): void {
  pending = null;
  cached = null;
}
