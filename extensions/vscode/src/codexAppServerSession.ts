import type { ChildProcessWithoutNullStreams } from "child_process";

import {
  CappedBytes,
  isJsonObject,
  JsonLineFramer,
  type JsonObject,
  ProtocolFrameTooLargeError,
  returnedThreadIdFrom,
  rpcErrorMessage,
} from "./codexAppServerProtocol";
import {
  closeCodexProcessTree,
  type CodexProcessCleanupOptions,
} from "./codexProcessCleanup";

export type CodexAppServerSessionOptions = CodexProcessCleanupOptions & {
  extensionVersion: string;
  startupTimeoutMs?: number;
  requestTimeoutMs?: number;
  batchTimeoutMs?: number;
  retainedDiagnosticBytes?: number;
  protocolFrameBytes?: number;
};

export type CodexAppServerCandidateOutcome =
  | { kind: "pre-dispatch-failure"; message: string }
  | {
      kind: "completed";
      registeredThreadIds: Set<string>;
      failures: Map<string, string>;
    };

type SessionPhase = "initializing" | "dispatched" | "cleaning" | "settled";

const DEFAULT_STARTUP_TIMEOUT_MS = 5_000;
const DEFAULT_REQUEST_TIMEOUT_MS = 5_000;
const DEFAULT_BATCH_TIMEOUT_MS = 10_000;
const DEFAULT_RETAINED_DIAGNOSTIC_BYTES = 8_192;
const DEFAULT_PROTOCOL_FRAME_BYTES = 65_536;

export function runCodexAppServerSession(
  child: ChildProcessWithoutNullStreams,
  threadIds: string[],
  options: CodexAppServerSessionOptions,
): Promise<CodexAppServerCandidateOutcome> {
  return new CandidateSession(child, threadIds, options).run();
}

class CandidateSession {
  private readonly stdoutFramer: JsonLineFramer;
  private readonly stdoutDiagnostic: CappedBytes;
  private readonly stderrDiagnostic: CappedBytes;
  private readonly pendingRequests = new Map<number, string>();
  private readonly requestTimers = new Map<number, NodeJS.Timeout>();
  private readonly terminalRequestIds = new Set<number>();
  private readonly registeredThreadIds = new Set<string>();
  private readonly failures = new Map<string, string>();
  private startupTimer: NodeJS.Timeout | undefined;
  private batchTimer: NodeJS.Timeout | undefined;
  private resolveOutcome: ((outcome: CodexAppServerCandidateOutcome) => void) | undefined;
  private phase: SessionPhase = "initializing";

  constructor(
    private readonly child: ChildProcessWithoutNullStreams,
    private readonly threadIds: string[],
    private readonly options: CodexAppServerSessionOptions,
  ) {
    const retainedBytes = boundedNonnegativeInteger(
      options.retainedDiagnosticBytes,
      DEFAULT_RETAINED_DIAGNOSTIC_BYTES,
    );
    this.stdoutDiagnostic = new CappedBytes(retainedBytes);
    this.stderrDiagnostic = new CappedBytes(retainedBytes);
    this.stdoutFramer = new JsonLineFramer(
      positiveInteger(options.protocolFrameBytes, DEFAULT_PROTOCOL_FRAME_BYTES),
    );
  }

  run(): Promise<CodexAppServerCandidateOutcome> {
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
    try {
      for (const line of this.stdoutFramer.push(bytes)) {
        if (this.isFinishing()) {
          return;
        }
        if (line.length > 0) {
          this.handleLine(line);
        }
      }
    } catch (error) {
      const message =
        error instanceof ProtocolFrameTooLargeError
          ? `Codex app-server stdout frame exceeded ${error.limit} bytes`
          : `Codex app-server stdout framing failed: ${errorMessage(error)}`;
      this.failSession(message);
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
    if (message.id === 1 && this.phase === "initializing") {
      this.handleInitializeResponse(message);
      return;
    }
    if (typeof message.id === "number") {
      if (this.pendingRequests.has(message.id)) {
        this.handleTaskResponse(message.id, message);
        return;
      }
      if (this.terminalRequestIds.has(message.id)) {
        return;
      }
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
      if (!this.writeMessage({ method: "initialized", params: {} })) {
        return;
      }
      this.dispatchTaskRequests();
    } catch (error) {
      this.failSession(`Could not write to Codex app-server: ${errorMessage(error)}`);
    }
  }

  private dispatchTaskRequests(): void {
    if (this.phase !== "initializing") {
      return;
    }
    const requestTimeoutMs = positiveInteger(this.options.requestTimeoutMs, DEFAULT_REQUEST_TIMEOUT_MS);
    const requests = this.threadIds.map((threadId, index) => ({
      id: index + 2,
      method: "thread/read",
      params: { threadId, includeTurns: false },
    }));
    for (const request of requests) {
      const requestId = request.id;
      this.pendingRequests.set(requestId, request.params.threadId);
      this.requestTimers.set(
        requestId,
        setTimeout(() => this.handleRequestTimeout(requestId), requestTimeoutMs),
      );
    }
    this.batchTimer = setTimeout(
      () => this.failUnresolved("Codex app-server batch timed out"),
      positiveInteger(this.options.batchTimeoutMs, DEFAULT_BATCH_TIMEOUT_MS),
    );
    if (!this.transitionTo("dispatched")) {
      this.clearTimers();
      this.pendingRequests.clear();
      return;
    }

    for (const request of requests) {
      if (!this.writeMessage(request)) {
        return;
      }
    }
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
    if (threadId === undefined || this.isFinishing()) {
      return;
    }
    this.failures.set(threadId, "Codex app-server thread/read request timed out");
    this.settleRequest(requestId);
  }

  private settleRequest(requestId: number): void {
    this.terminalRequestIds.add(requestId);
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
    if (this.isFinishing()) {
      return;
    }
    const diagnosticMessage = this.withStderr(message);
    for (const [requestId, threadId] of this.pendingRequests) {
      this.terminalRequestIds.add(requestId);
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
    if (this.isFinishing()) {
      return;
    }
    if (this.phase === "dispatched") {
      this.failUnresolved(message);
      return;
    }
    this.finish({ kind: "pre-dispatch-failure", message: this.withStderr(message) });
  }

  private writeMessage(message: JsonObject): boolean {
    if (this.isFinishing()) {
      return false;
    }
    this.child.stdin.write(`${JSON.stringify(message)}\n`);
    return !this.hasSettled();
  }

  private withStderr(message: string): string {
    const stderr = this.stderrDiagnostic.text();
    return stderr ? `${message} (stderr: ${stderr})` : message;
  }

  private hasSettled(): boolean {
    return this.isFinishing();
  }

  private isFinishing(): boolean {
    return this.phase === "cleaning" || this.phase === "settled";
  }

  private transitionTo(nextPhase: Exclude<SessionPhase, "initializing">): boolean {
    const phaseOrder: Record<SessionPhase, number> = {
      initializing: 0,
      dispatched: 1,
      cleaning: 2,
      settled: 3,
    };
    if (phaseOrder[nextPhase] <= phaseOrder[this.phase]) {
      return false;
    }
    this.phase = nextPhase;
    return true;
  }

  private finish(outcome: CodexAppServerCandidateOutcome): void {
    if (!this.transitionTo("cleaning")) {
      return;
    }
    this.clearTimers();
    this.removeListeners();
    const resolve = this.resolveOutcome;
    this.resolveOutcome = undefined;
    void closeCodexProcessTree(this.child, this.options).finally(() => {
      if (this.transitionTo("settled")) {
        resolve?.(outcome);
      }
    });
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

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function positiveInteger(value: number | undefined, fallback: number): number {
  return value !== undefined && Number.isInteger(value) && value > 0 ? value : fallback;
}

function boundedNonnegativeInteger(value: number | undefined, fallback: number): number {
  return value !== undefined && Number.isInteger(value) && value >= 0 ? value : fallback;
}
