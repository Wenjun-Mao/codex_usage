import type {
  TaskTransferPort,
  TransferExecutionRequest,
  TransferReviewRequest,
} from "../src/taskTransfer";

declare const reviewBoundary: Pick<TaskTransferPort, "review">;
declare const executionRequest: TransferExecutionRequest;
declare const reviewRequest: TransferReviewRequest;

void reviewBoundary.review(reviewRequest);

// @ts-expect-error Transfer execution requests must not cross the Review boundary.
void reviewBoundary.review(executionRequest);
