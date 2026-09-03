import { invoke } from "@tauri-apps/api/core";
import type { UpdateInfo } from "./types";
import { fixtureRequest } from "./fixtures";

export interface AgentRequest {
  method: "GET" | "POST";
  path: string;
  body?: Record<string, unknown>;
}

export interface CodexHomeStatus {
  codex_home: string;
  valid: boolean;
  issue: string;
}

const inTauri = "__TAURI_INTERNALS__" in window;

export async function ensureAgent(): Promise<void> {
  if (inTauri) {
    await invoke("ensure_agent");
  }
}

export async function codexHomeStatus(): Promise<CodexHomeStatus> {
  if (!inTauri) {
    return { codex_home: "/Users/demo/.codex", valid: true, issue: "" };
  }
  return invoke<CodexHomeStatus>("codex_home_status");
}

export async function prepareCodexHome(path: string): Promise<void> {
  if (inTauri) {
    await invoke("prepare_codex_home", { path });
  }
}

export async function agentRequest<T>(request: AgentRequest): Promise<T> {
  if (!inTauri) {
    return fixtureRequest<T>(request);
  }
  return invoke<T>("agent_request", { request });
}

export async function chooseDirectory(title: string): Promise<string | null> {
  if (!inTauri) {
    return "/Users/demo/.codex";
  }
  return invoke<string | null>("choose_directory", { title });
}

export async function configureBackground(enabled: boolean): Promise<void> {
  if (inTauri) {
    await invoke("configure_background", { enabled });
  }
}

export async function switchCodexHome(path: string): Promise<void> {
  if (inTauri) {
    await invoke("switch_codex_home", { path });
  }
}

export async function resetLocalData(): Promise<void> {
  if (inTauri) {
    await invoke("reset_local_data");
  }
}

export async function revealPath(path: string): Promise<void> {
  if (inTauri) {
    await invoke("reveal_path", { path });
  }
}

export async function checkForUpdate(): Promise<UpdateInfo> {
  if (!inTauri) {
    return {
      available: false,
      current_version: "2.0.0",
      version: "2.0.0",
      date: null,
      body: null,
    };
  }
  return invoke<UpdateInfo>("check_for_update");
}

export async function installUpdate(): Promise<void> {
  if (inTauri) {
    await invoke("install_update");
  }
}

export function isNativeHost(): boolean {
  return inTauri;
}
