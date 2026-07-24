export type JsonObject = Record<string, unknown>;

export class ProtocolFrameTooLargeError extends Error {
  constructor(readonly limit: number) {
    super(`Protocol frame exceeded ${limit} bytes`);
    this.name = "ProtocolFrameTooLargeError";
  }
}

export class JsonLineFramer {
  private pending = Buffer.alloc(0);

  constructor(private readonly limit: number) {}

  push(chunk: Buffer): string[] {
    const lines: string[] = [];
    let frameStart = 0;
    for (let index = 0; index < chunk.length; index += 1) {
      if (chunk[index] !== 0x0a) {
        continue;
      }
      const frame = this.completeFrame(chunk.subarray(frameStart, index));
      const contentEnd = frame.at(-1) === 0x0d ? frame.length - 1 : frame.length;
      lines.push(frame.subarray(0, contentEnd).toString("utf8"));
      frameStart = index + 1;
    }
    this.appendIncomplete(chunk.subarray(frameStart));
    return lines;
  }

  private completeFrame(suffix: Buffer): Buffer {
    this.assertWithinLimit(suffix.length);
    const frame =
      this.pending.length === 0 ? Buffer.from(suffix) : Buffer.concat([this.pending, suffix], this.pending.length + suffix.length);
    this.pending = Buffer.alloc(0);
    return frame;
  }

  private appendIncomplete(suffix: Buffer): void {
    if (suffix.length === 0) {
      return;
    }
    this.assertWithinLimit(suffix.length);
    this.pending =
      this.pending.length === 0 ? Buffer.from(suffix) : Buffer.concat([this.pending, suffix], this.pending.length + suffix.length);
  }

  private assertWithinLimit(additionalBytes: number): void {
    if (this.pending.length + additionalBytes > this.limit) {
      throw new ProtocolFrameTooLargeError(this.limit);
    }
  }
}

export class CappedBytes {
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

export function isJsonObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function returnedThreadIdFrom(result: unknown): string | undefined {
  if (!isJsonObject(result) || !isJsonObject(result.thread)) {
    return undefined;
  }
  return typeof result.thread.id === "string" ? result.thread.id : undefined;
}

export function rpcErrorMessage(error: unknown): string {
  if (isJsonObject(error) && typeof error.message === "string") {
    return error.message;
  }
  return "unknown JSON-RPC error";
}
