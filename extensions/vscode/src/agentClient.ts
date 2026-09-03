import * as fs from "fs/promises";
import * as http from "http";
import * as os from "os";
import * as path from "path";

const API_VERSION = 1;
const MAX_REQUEST_BYTES = 2 * 1024 * 1024;
const MAX_RESPONSE_BYTES = 64 * 1024 * 1024;

interface AgentDescriptor {
  api_version: number;
  port: number;
  token: string;
  codex_home: string;
}

interface AgentSettingsFile {
  codex_home?: unknown;
}

export class AgentUnavailableError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AgentUnavailableError";
  }
}

export class AgentClient {
  private constructor(private readonly descriptor: AgentDescriptor) {}

  static async discover(environment: NodeJS.ProcessEnv = process.env): Promise<AgentClient> {
    const codexHome = await resolveCodexHome(environment);
    const descriptorPath = path.join(codexHome, ".codex-usage", "agent.json");
    let descriptor: AgentDescriptor;
    try {
      descriptor = parseDescriptor(JSON.parse(await fs.readFile(descriptorPath, "utf8")));
    } catch (error) {
      throw new AgentUnavailableError(`Collector descriptor unavailable: ${errorMessage(error)}`);
    }
    if (!samePath(descriptor.codex_home, codexHome)) {
      throw new AgentUnavailableError("Collector descriptor belongs to a different Codex home.");
    }
    const client = new AgentClient(descriptor);
    const health = await client.request<{ api_version: number; ok: boolean }>("GET", "/v1/health", undefined, 2_000);
    if (!health.ok || health.api_version !== API_VERSION) {
      throw new AgentUnavailableError("Collector API is unavailable or incompatible.");
    }
    return client;
  }

  get<T>(requestPath: string): Promise<T> {
    return this.request<T>("GET", requestPath);
  }

  post<T>(requestPath: string, body: Record<string, unknown> = {}): Promise<T> {
    return this.request<T>("POST", requestPath, body);
  }

  private request<T>(method: "GET" | "POST", requestPath: string, body?: Record<string, unknown>, timeoutMs?: number): Promise<T> {
    if (!requestPath.startsWith("/v1/") || requestPath.includes("://") || /[\r\n]/u.test(requestPath)) {
      return Promise.reject(new Error("Invalid collector request path."));
    }
    const encoded = body === undefined ? undefined : Buffer.from(JSON.stringify(body));
    if (encoded && encoded.length > MAX_REQUEST_BYTES) {
      return Promise.reject(new Error("Collector request body exceeds the companion limit."));
    }
    return new Promise((resolve, reject) => {
      const request = http.request({
        host: "127.0.0.1",
        port: this.descriptor.port,
        path: requestPath,
        method,
        headers: {
          Authorization: `Bearer ${this.descriptor.token}`,
          "Content-Type": "application/json",
          ...(encoded ? { "Content-Length": encoded.length } : {}),
        },
        ...(timeoutMs === undefined ? {} : { timeout: timeoutMs }),
      }, (response) => {
        const declaredLength = Number(response.headers["content-length"] ?? 0);
        if (Number.isFinite(declaredLength) && declaredLength > MAX_RESPONSE_BYTES) {
          request.destroy(new Error("Collector response exceeded the companion limit."));
          return;
        }
        const chunks: Buffer[] = [];
        let size = 0;
        response.on("data", (chunk: Buffer) => {
          size += chunk.length;
          if (size > MAX_RESPONSE_BYTES) {
            request.destroy(new Error("Collector response exceeded the companion limit."));
            return;
          }
          chunks.push(chunk);
        });
        response.on("end", () => {
          try {
            const payload = JSON.parse(Buffer.concat(chunks).toString("utf8")) as unknown;
            if ((response.statusCode ?? 500) >= 400) {
              const detail = isRecord(payload) && typeof payload.error === "string" ? payload.error : "Collector request failed.";
              reject(new Error(detail));
            } else {
              resolve(payload as T);
            }
          } catch (error) {
            reject(new Error(`Collector returned invalid JSON: ${errorMessage(error)}`));
          }
        });
      });
      request.on("timeout", () => request.destroy(new Error("Collector health check timed out.")));
      request.on("error", (error) => reject(new AgentUnavailableError(error.message)));
      if (encoded) request.write(encoded);
      request.end();
    });
  }
}

export async function resolveCodexHome(environment: NodeJS.ProcessEnv = process.env): Promise<string> {
  const settings = settingsFilePath(environment);
  try {
    const payload = JSON.parse(await fs.readFile(settings, "utf8")) as AgentSettingsFile;
    if (typeof payload.codex_home === "string" && payload.codex_home.trim()) {
      return path.resolve(expandHome(payload.codex_home.trim()));
    }
  } catch (error) {
    if (!isMissingFile(error)) throw error;
  }
  const configured = environment.CODEX_HOME?.trim();
  return path.resolve(expandHome(configured || path.join(os.homedir(), ".codex")));
}

export function settingsFilePath(environment: NodeJS.ProcessEnv = process.env): string {
  const override = environment.CODEX_USAGE_DATA_DIR?.trim();
  if (override) return path.join(expandHome(override), "settings.json");
  if (process.platform === "darwin") return path.join(os.homedir(), "Library", "Application Support", "Codex Usage", "settings.json");
  if (process.platform === "win32") return path.join(environment.LOCALAPPDATA || path.join(os.homedir(), "AppData", "Local"), "Codex Usage", "settings.json");
  return path.join(environment.XDG_CONFIG_HOME || path.join(os.homedir(), ".config"), "codex-usage", "settings.json");
}

export function samePath(
  left: string,
  right: string,
  platform: NodeJS.Platform = process.platform,
): boolean {
  const normalizedLeft = path.resolve(left);
  const normalizedRight = path.resolve(right);
  return platform === "win32"
    ? normalizedLeft.toLocaleLowerCase() === normalizedRight.toLocaleLowerCase()
    : normalizedLeft === normalizedRight;
}

function parseDescriptor(value: unknown): AgentDescriptor {
  if (!isRecord(value) || value.api_version !== API_VERSION || typeof value.port !== "number" || !Number.isInteger(value.port) || value.port < 1 || value.port > 65535 || typeof value.token !== "string" || value.token.length < 32 || typeof value.codex_home !== "string") {
    throw new Error("descriptor has invalid connection details");
  }
  return value as unknown as AgentDescriptor;
}

function expandHome(value: string): string {
  if (value === "~") return os.homedir();
  return value.startsWith(`~${path.sep}`) ? path.join(os.homedir(), value.slice(2)) : value;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isMissingFile(error: unknown): boolean {
  return isRecord(error) && error.code === "ENOENT";
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
