import type { CodexTaskRegistrationResult } from "./codexAppServer";
import type {
  DesktopProjectBindingOutcome,
  DesktopProjectBindingPlan,
  DesktopProjectBindingResult,
} from "./codexDesktopProjectBinding";
import type { SyncRunResult } from "./syncProtocol";
import {
  certifiedImportThreadIds,
  formatTaskRegistrationFailureLog,
} from "./taskTransferRegistration";
import type { TransferTransientStatus } from "./transferPresentation";

export type ImportedTaskIntegrationResult = {
  registration?: CodexTaskRegistrationResult;
  binding?: DesktopProjectBindingOutcome;
};

type ImportedTaskIntegrationPort = {
  registerImportedTasks(threadIds: readonly string[]): Promise<CodexTaskRegistrationResult>;
  bindImportedTasks(
    plan: DesktopProjectBindingPlan,
    registeredThreadIds: readonly string[],
  ): Promise<DesktopProjectBindingResult>;
  log(message: string): void;
  setTransientStatus(status: TransferTransientStatus | undefined): void;
};

export async function integrateImportedTasks(
  result: SyncRunResult,
  selectedThreadIds: readonly string[],
  bindingPlan: DesktopProjectBindingPlan,
  port: ImportedTaskIntegrationPort,
): Promise<ImportedTaskIntegrationResult> {
  const certifiedThreadIds = certifiedImportThreadIds(result, selectedThreadIds);
  if (certifiedThreadIds.length === 0) {
    return {};
  }

  port.setTransientStatus("registering");
  const registration = await registerTasks(certifiedThreadIds, port);
  for (const failure of registration.failures) {
    port.log(formatTaskRegistrationFailureLog(failure.threadId));
  }

  port.setTransientStatus("binding");
  let binding: DesktopProjectBindingOutcome;
  try {
    binding = await port.bindImportedTasks(bindingPlan, registration.registeredThreadIds);
  } catch (error) {
    const code = error instanceof Error && "code" in error &&
      typeof error.code === "string" ? error.code : "binding-failed";
    binding = {
      status: "failed",
      attempted: registration.registeredThreadIds.length,
      bound: 0,
      code,
    };
    port.log(`[desktop project binding:${code}] Assignment was not completed`);
  }
  return { registration, binding };
}

async function registerTasks(
  threadIds: readonly string[],
  port: Pick<ImportedTaskIntegrationPort, "registerImportedTasks">,
): Promise<CodexTaskRegistrationResult> {
  try {
    return await port.registerImportedTasks(threadIds);
  } catch {
    return {
      attemptedThreadIds: [...threadIds],
      registeredThreadIds: [],
      failures: threadIds.map((threadId) => ({
        threadId,
        message: "Codex registration could not be completed",
      })),
    };
  }
}
