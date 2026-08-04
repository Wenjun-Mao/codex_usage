export type RefreshRequestOutcome = "published" | "superseded";

/**
 * Async publishers must route every synchronous external side effect through
 * commit so currency is checked at the actual publication point. Two-argument
 * publishers remain supported for existing synchronous callbacks.
 */
export type RefreshPublication = {
  isCurrent: () => boolean;
  commit: (sideEffect: () => void) => boolean;
};

type RefreshEntry<Request> = {
  request: Request;
  generation: number;
  resolve: (outcome: RefreshRequestOutcome) => void;
  reject: (error: unknown) => void;
};

export class LatestRefreshCoordinator<Request, Result> {
  private active: RefreshEntry<Request> | undefined;
  private pending: RefreshEntry<Request> | undefined;
  private latestGeneration = 0;

  constructor(
    private readonly execute: (request: Request) => Promise<Result>,
    private readonly publish: (
      request: Request,
      result: Result,
      publication: RefreshPublication,
    ) => Promise<void> | void,
  ) {}

  request(request: Request): Promise<RefreshRequestOutcome> {
    const entry = this.createEntry(request);
    if (!this.active) {
      this.start(entry);
      return entry.promise;
    }

    this.pending?.resolve("superseded");
    this.pending = entry;
    return entry.promise;
  }

  private createEntry(request: Request): RefreshEntry<Request> & { promise: Promise<RefreshRequestOutcome> } {
    let resolve: (outcome: RefreshRequestOutcome) => void = () => undefined;
    let reject: (error: unknown) => void = () => undefined;
    const promise = new Promise<RefreshRequestOutcome>((resolvePromise, rejectPromise) => {
      resolve = resolvePromise;
      reject = rejectPromise;
    });
    return { request, generation: ++this.latestGeneration, promise, resolve, reject };
  }

  private start(entry: RefreshEntry<Request>): void {
    this.active = entry;
    void this.run(entry);
  }

  private async run(entry: RefreshEntry<Request>): Promise<void> {
    const publication = this.publicationFor(entry);
    try {
      const result = await this.execute(entry.request);
      if (!publication.isCurrent()) {
        entry.resolve("superseded");
        return;
      }
      await this.publish(entry.request, result, publication);
      entry.resolve(publication.isCurrent() ? "published" : "superseded");
    } catch (error) {
      if (!publication.isCurrent()) {
        entry.resolve("superseded");
      } else {
        entry.reject(error);
      }
    } finally {
      this.active = undefined;
      const next = this.pending;
      this.pending = undefined;
      if (next) {
        this.start(next);
      }
    }
  }

  private publicationFor(entry: RefreshEntry<Request>): RefreshPublication {
    const isCurrent = (): boolean => entry.generation === this.latestGeneration;
    return {
      isCurrent,
      commit: (sideEffect): boolean => {
        if (!isCurrent()) {
          return false;
        }
        sideEffect();
        return true;
      },
    };
  }
}
