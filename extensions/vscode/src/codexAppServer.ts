import { spawn, type ChildProcessWithoutNullStreams } from "child_process";
import type { Readable, Writable } from "stream";
import { StringDecoder } from "string_decoder";

import type { CodexExecutableCandidate } from "./codexExecutableDiscovery";

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

export type CodexAppServerOptions = {
  candidates: CodexExecutableCandidate[];
  threadIds: readonly string[];
  extensionVersion: string;
  spawnProcess?: CodexAppServerSpawner;
  startupTimeoutMs?: number;
  requestTimeoutMs?: number;
  batchTimeoutMs?: number;
  retainedDiagnosticBytes?: number;
};

type CandidateOutcome =
  | { kind: "pre-dispatch-failure"; message: string }
  | {
      kind: "completed";
      registeredThreadIds: Set<string>;
      failures: Map<string, string>;
    };

type JsonObject = Record<string, unknown>;

const DEFAULT_STARTUP_TIMEOUT_MS = 5_000;
const DEFAULT_REQUEST_TIMEOUT_MS = 5_000;
const DEFAULT_BATCH_TIMEOUT_MS = 10_000;
const DEFAULT_RETAINED_DIAGNOSTIC_BYTES = 8_192;
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

    const session = new CandidateSession(child, validThreadIds, options);
    const outcome = await session.run();
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

class CandidateSession {
  private readonly decoder = new StringDecoder("utf8");
  private readonly stdoutDiagnostic: CappedBytes;
  private readonly stderrDiagnostic: CappedBytes;
  private readonly pendingRequests = new Map<number, string>();
  private readonly requestTimers = new Map<number, NodeJS.Timeout>();
  private readonly registeredThreadIds = new Set<string>();
  private readonly failures = new Map<string, string>();
  private stdoutBuffer = "";
  private startupTimer: NodeJS.Timeout | undefined;
  private batchTimer: NodeJS.Timeout | undefined;
  private resolveOutcome: ((outcome: CandidateOutcome) => void) | undefined;
  private taskDispatched = false;
  private settled = false;

  constructor(
    private readonly child: ChildProcessWithoutNullStreams,
    private readonly threadIds: string[],
    private readonly options: CodexAppServerOptions,
  ) {
    const retainedBytes = boundedNonnegativeInteger(
      options.retainedDiagnosticBytes,
      DEFAULT_RETAINED_DIAGNOSTIC_BYTES,
    );
    this.stdoutDiagnostic = new CappedBytes(retainedBytes);
    this.stderrDiagnostic = new CappedBytes(retainedBytes);
  }

  run(): Promise<CandidateOutcome> {
    return new Promise((resolve) => {
      this.resolveOutcome = resolve;
      this.attachListeners();
      this.startupTimer = setTimeout(
        () => this.failSession("Codex app-server initialization timed out"),
        positiveInteger(this.options.startupTimeoutMs, DEFAULT_STARTUP_TIMEOUT_MS),
      );
      try {
        this.writeMessage({
          id: 1,
          method: "initialize",
          params: {
            clientInfo: { name: "codex-usage", version: this.options.extensionVersion },
            capabilities: {},
          },
        });
      } catch (error) {
        this.failSession(`Could not initialize Codex app-server: ${errorMessage(error)}`);
      }
    });
  }

  private readonly onStdoutData = (chunk: Buffer | string): void => {
    const bytes = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    this.stdoutDiagnostic.append(bytes);
    this.stdoutBuffer += this.decoder.write(bytes);
    let newlineIndex: number;
    while ((newlineIndex = this.stdoutBuffer.indexOf("\n")) >= 0 && !this.settled) {
      const rawLine = this.stdoutBuffer.slice(0, newlineIndex);
      this.stdoutBuffer = this.stdoutBuffer.slice(newlineIndex + 1);
      const line = rawLine.endsWith("\r") ? rawLine.slice(0, -1) : rawLine;
      if (line.length > 0) {
        this.handleLine(line);
      }
    }
  };

  private readonly onStderrData = (chunk: Buffer | string): void => {
    this.stderrDiagnostic.append(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
  };

  private readonly onProcessError = (error: Error): void => {
    this.failSession(`Codex app-server process error: ${error.message}`);
  };

  private readonly onProcessExit = (code: number | null, signal: NodeJS.Signals | null): void => {
    const status = code === null ? `signal ${signal ?? "unknown"}` : `code ${code}`;
    this.failSession(`Codex app-server exited early with ${status}`);
  };

  private readonly onStdinError = (error: Error): void => {
    this.failSession(`Codex app-server stdin error: ${error.message}`);
  };

  private attachListeners(): void {
    this.child.stdout.on("data", this.onStdoutData);
    this.child.stderr.on("data", this.onStderrData);
    this.child.stdin.on("error", this.onStdinError);
    this.child.on("error", this.onProcessError);
    this.child.on("exit", this.onProcessExit);
  }

  private handleLine(line: string): void {
    let message: unknown;
    try {
      message = JSON.parse(line);
    } catch {
      this.failSession("Codex app-server emitted malformed JSON on stdout");
      return;
    }
    if (!isJsonObject(message)) {
      this.failSession("Codex app-server emitted a non-object protocol message");
      return;
    }
    if (!Object.hasOwn(message, "id")) {
      if (typeof message.method === "string") {
        return;
      }
      this.failSession("Codex app-server emitted an invalid notification");
      return;
    }
    if (message.id === 1 && !this.taskDispatched) {
      this.handleInitializeResponse(message);
      return;
    }
    if (typeof message.id === "number" && this.pendingRequests.has(message.id)) {
      this.handleTaskResponse(message.id, message);
      return;
    }
    this.failSession("Codex app-server emitted a response with an unexpected request id");
  }

  private handleInitializeResponse(message: JsonObject): void {
    if (this.startupTimer) {
      clearTimeout(this.startupTimer);
      this.startupTimer = undefined;
    }
    if (Object.hasOwn(message, "error")) {
      this.failSession(`Codex app-server initialization failed: ${rpcErrorMessage(message.error)}`);
      return;
    }
    if (!Object.hasOwn(message, "result")) {
      this.failSession("Codex app-server initialization response had no result");
      return;
    }

    try {
      this.writeMessage({ method: "initialized", params: {} });
      this.dispatchTaskRequests();
    } catch (error) {
      this.failSession(`Could not write to Codex app-server: ${errorMessage(error)}`);
    }
  }

  private dispatchTaskRequests(): void {
    const requestTimeoutMs = positiveInteger(this.options.requestTimeoutMs, DEFAULT_REQUEST_TIMEOUT_MS);
    for (const [index, threadId] of this.threadIds.entries()) {
      const requestId = index + 2;
      this.pendingRequests.set(requestId, threadId);
      this.writeMessage({
        id: requestId,
        method: "thread/read",
        params: { threadId, includeTurns: false },
      });
      this.taskDispatched = true;
      this.requestTimers.set(
        requestId,
        setTimeout(() => this.handleRequestTimeout(requestId), requestTimeoutMs),
      );
    }
    this.batchTimer = setTimeout(
      () => this.failUnresolved("Codex app-server batch timed out"),
      positiveInteger(this.options.batchTimeoutMs, DEFAULT_BATCH_TIMEOUT_MS),
    );
  }

  private handleTaskResponse(requestId: number, message: JsonObject): void {
    const threadId = this.pendingRequests.get(requestId);
    if (threadId === undefined) {
      return;
    }
    if (Object.hasOwn(message, "error")) {
      this.failures.set(threadId, `thread/read failed: ${rpcErrorMessage(message.error)}`);
      this.settleRequest(requestId);
      return;
    }
    const returnedThreadId = returnedThreadIdFrom(message.result);
    if (returnedThreadId !== threadId) {
      const received = returnedThreadId === undefined ? "missing" : JSON.stringify(returnedThreadId);
      this.failures.set(threadId, `thread/read returned ${received}; expected ${JSON.stringify(threadId)}`);
    } else {
      this.registeredThreadIds.add(threadId);
    }
    this.settleRequest(requestId);
  }

  private handleRequestTimeout(requestId: number): void {
    const threadId = this.pendingRequests.get(requestId);
    if (threadId === undefined || this.settled) {
      return;
    }
    this.failures.set(threadId, "Codex app-server thread/read request timed out");
    this.settleRequest(requestId);
  }

  private settleRequest(requestId: number): void {
    this.pendingRequests.delete(requestId);
    const timer = this.requestTimers.get(requestId);
    if (timer) {
      clearTimeout(timer);
      this.requestTimers.delete(requestId);
    }
    if (this.pendingRequests.size === 0) {
      this.finish({
        kind: "completed",
        registeredThreadIds: this.registeredThreadIds,
        failures: this.failures,
      });
    }
  }

  private failUnresolved(message: string): void {
    if (this.settled) {
      return;
    }
    const diagnosticMessage = this.withStderr(message);
    for (const [requestId, threadId] of this.pendingRequests) {
      this.failures.set(threadId, diagnosticMessage);
      const timer = this.requestTimers.get(requestId);
      if (timer) {
        clearTimeout(timer);
        this.requestTimers.delete(requestId);
      }
    }
    this.pendingRequests.clear();
    this.finish({
      kind: "completed",
      registeredThreadIds: this.registeredThreadIds,
      failures: this.failures,
    });
  }

  private failSession(message: string): void {
    if (this.settled) {
      return;
    }
    if (this.taskDispatched) {
      this.failUnresolved(message);
      return;
    }
    this.finish({ kind: "pre-dispatch-failure", message: this.withStderr(message) });
  }

  private writeMessage(message: JsonObject): void {
    this.child.stdin.write(`${JSON.stringify(message)}\n`);
  }

  private withStderr(message: string): string {
    const stderr = this.stderrDiagnostic.text();
    return stderr ? `${message} (stderr: ${stderr})` : message;
  }

  private finish(outcome: CandidateOutcome): void {
    if (this.settled) {
      return;
    }
    this.settled = true;
    this.clearTimers();
    this.removeListeners();
    try {
      this.child.stdin.end();
    } catch {
      // The process is terminated below even when its stdin has already failed.
    }
    try {
      this.child.kill();
    } catch {
      // Cleanup is best-effort after the result boundary has been determined.
    }
    this.resolveOutcome?.(outcome);
  }

  private clearTimers(): void {
    if (this.startupTimer) {
      clearTimeout(this.startupTimer);
      this.startupTimer = undefined;
    }
    if (this.batchTimer) {
      clearTimeout(this.batchTimer);
      this.batchTimer = undefined;
    }
    for (const timer of this.requestTimers.values()) {
      clearTimeout(timer);
    }
    this.requestTimers.clear();
  }

  private removeListeners(): void {
    this.child.stdout.removeListener("data", this.onStdoutData);
    this.child.stderr.removeListener("data", this.onStderrData);
    this.child.stdin.removeListener("error", this.onStdinError);
    this.child.removeListener("error", this.onProcessError);
    this.child.removeListener("exit", this.onProcessExit);
  }
}

class CappedBytes {
  private retained = Buffer.alloc(0);

  constructor(private readonly limit: number) {}

  append(chunk: Buffer): void {
    if (this.limit === 0) {
      return;
    }
    if (chunk.length >= this.limit) {
      this.retained = Buffer.from(chunk.subarray(chunk.length - this.limit));
      return;
    }
    const combined = Buffer.concat([this.retained, chunk]);
    this.retained =
      combined.length <= this.limit ? combined : Buffer.from(combined.subarray(combined.length - this.limit));
  }

  text(): string {
    return this.retained.toString("utf8").trim();
  }
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

function isJsonObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function returnedThreadIdFrom(result: unknown): string | undefined {
  if (!isJsonObject(result) || !isJsonObject(result.thread)) {
    return undefined;
  }
  return typeof result.thread.id === "string" ? result.thread.id : undefined;
}

function rpcErrorMessage(error: unknown): string {
  if (isJsonObject(error) && typeof error.message === "string") {
    return error.message;
  }
  return "unknown JSON-RPC error";
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function positiveInteger(value: number | undefined, fallback: number): number {
  return value !== undefined && Number.isInteger(value) && value > 0 ? value : fallback;
}

function boundedNonnegativeInteger(value: number | undefined, fallback: number): number {
  return value !== undefined && Number.isInteger(value) && value >= 0 ? value : fallback;
}
