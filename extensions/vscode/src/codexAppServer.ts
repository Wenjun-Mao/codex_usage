import { spawn, type ChildProcessWithoutNullStreams } from "child_process";

import type { CodexExecutableCandidate } from "./codexExecutableDiscovery";
import {
  runCodexAppServerSession,
  type CodexAppServerSessionOptions,
} from "./codexAppServerSession";

export type CodexRegistrationFailure = {
  threadId: string;
  message: string;
};

export type CodexTaskRegistrationResult = {
  attemptedThreadIds: string[];
  registeredThreadIds: string[];
  failures: CodexRegistrationFailure[];
  executable?: CodexExecutableCandidate;
};

type SpawnOptions = {
  shell: false;
  stdio: ["pipe", "pipe", "pipe"];
};

export type CodexAppServerSpawner = (
  executablePath: string,
  args: readonly string[],
  options: SpawnOptions,
) => ChildProcessWithoutNullStreams;

export type CodexAppServerOptions = CodexAppServerSessionOptions & {
  candidates: CodexExecutableCandidate[];
  threadIds: readonly string[];
  spawnProcess?: CodexAppServerSpawner;
};

const INVALID_THREAD_ID_MESSAGE = "Thread id must be nonempty and contain no surrounding whitespace";

export async function registerCodexTasks(options: CodexAppServerOptions): Promise<CodexTaskRegistrationResult> {
  const { validThreadIds, validationFailures } = classifyThreadIds(options.threadIds);
  const resultBase = {
    attemptedThreadIds: validThreadIds,
    registeredThreadIds: [] as string[],
    failures: validationFailures,
  };
  if (validThreadIds.length === 0) {
    return resultBase;
  }

  const spawnProcess = options.spawnProcess ?? defaultSpawner;
  let lastPreDispatchFailure = "No Codex executable candidate was available";

  for (const candidate of options.candidates) {
    let child: ChildProcessWithoutNullStreams;
    try {
      child = spawnProcess(candidate.executablePath, ["app-server", "--stdio"], {
        shell: false,
        stdio: ["pipe", "pipe", "pipe"],
      });
    } catch (error) {
      lastPreDispatchFailure = `Could not start Codex app-server: ${errorMessage(error)}`;
      continue;
    }

    const outcome = await runCodexAppServerSession(child, validThreadIds, options);
    if (outcome.kind === "pre-dispatch-failure") {
      lastPreDispatchFailure = outcome.message;
      continue;
    }

    return {
      ...resultBase,
      registeredThreadIds: validThreadIds.filter((threadId) => outcome.registeredThreadIds.has(threadId)),
      failures: [
        ...validationFailures,
        ...validThreadIds
          .filter((threadId) => outcome.failures.has(threadId))
          .map((threadId) => ({ threadId, message: outcome.failures.get(threadId) as string })),
      ],
      executable: candidate,
    };
  }

  return {
    ...resultBase,
    failures: [
      ...validationFailures,
      ...validThreadIds.map((threadId) => ({ threadId, message: lastPreDispatchFailure })),
    ],
  };
}

function classifyThreadIds(threadIds: readonly string[]): {
  validThreadIds: string[];
  validationFailures: CodexRegistrationFailure[];
} {
  const seen = new Set<string>();
  const validThreadIds: string[] = [];
  const validationFailures: CodexRegistrationFailure[] = [];
  for (const threadId of threadIds) {
    if (seen.has(threadId)) {
      continue;
    }
    seen.add(threadId);
    if (threadId.length === 0 || threadId !== threadId.trim()) {
      validationFailures.push({ threadId, message: INVALID_THREAD_ID_MESSAGE });
    } else {
      validThreadIds.push(threadId);
    }
  }
  return { validThreadIds, validationFailures };
}

function defaultSpawner(executablePath: string, args: readonly string[], options: SpawnOptions): ChildProcessWithoutNullStreams {
  return spawn(executablePath, [...args], options);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
