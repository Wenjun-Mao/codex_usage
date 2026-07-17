type PlannerRow = {
  thread_id: string;
  state: string;
  action: string;
};

type ValidationFailure = (message: string) => never;

const PLANNER_ACTION_BY_STATE = new Map<string, string>([
  ["synced", "none"],
  ["local_only", "push"],
  ["remote_only", "pull"],
  ["missing", "skip"],
  ["local_ahead", "push"],
  ["remote_ahead", "pull"],
  ["fast_forward_push", "push"],
  ["fast_forward_pull", "pull"],
  ["conflict", "conflict"],
  ["issue", "issue"],
  ["project_rebind", "pull"],
]);

export function requireValidPlannerRows<T extends PlannerRow>(
  rows: T[],
  invalid: ValidationFailure,
): T[] {
  const seenIds = new Set<string>();
  rows.forEach((row, index) => {
    const label = `threads[${index}]`;
    if (!row.thread_id || row.thread_id !== row.thread_id.trim()) {
      invalid(`${label}.thread_id must be nonempty and equal to its trim`);
    }
    if (seenIds.has(row.thread_id)) {
      invalid(`${label}.thread_id duplicates task id ${JSON.stringify(row.thread_id)}`);
    }
    seenIds.add(row.thread_id);

    const expectedAction = PLANNER_ACTION_BY_STATE.get(row.state);
    if (expectedAction === undefined || row.action !== expectedAction) {
      invalid(
        `${label} has invalid planner state/action pair ` +
          `${JSON.stringify(row.state)}/${JSON.stringify(row.action)}`,
      );
    }
  });
  return rows;
}
