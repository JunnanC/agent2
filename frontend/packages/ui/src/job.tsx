import { Icon } from "./icons";

export type JobStageState = "pending" | "running" | "done" | "failed";

export interface JobStage {
  key: string;
  label: string;
  state: JobStageState;
  detail?: string;
}

export type AsyncJobStatus = "submitted" | "processing" | "succeeded" | "failed" | "unknown";

export interface AsyncJobProgressProps {
  status: AsyncJobStatus;
  stages: JobStage[];
  failureReason?: string;
  onRetry?: () => void;
}

const STATUS_LABEL: Record<AsyncJobStatus, string> = {
  submitted: "已提交",
  processing: "处理中",
  succeeded: "成功",
  failed: "失败",
  unknown: "未知状态",
};

const STATUS_TONE: Record<AsyncJobStatus, string> = {
  submitted: "blue",
  processing: "blue",
  succeeded: "good",
  failed: "bad",
  unknown: "neutral",
};

export function AsyncJobProgress({ status, stages, failureReason, onRetry }: AsyncJobProgressProps) {
  return (
    <div className="job-progress" role="status" aria-live="polite">
      <div className="panel-title" style={{ marginBottom: 4 }}>
        <span className={`status ${STATUS_TONE[status]}`}>{STATUS_LABEL[status]}</span>
      </div>
      {stages.map((stage) => (
        <div key={stage.key} className={`job-stage ${stage.state}`}>
          <span aria-hidden="true">
            {stage.state === "done" ? "✓" : stage.state === "failed"
              ? <Icon name="alert-triangle" size={12} /> : stage.state === "running" ? "…" : ""}
          </span>
          <span style={{ minWidth: 0 }}>
            <strong style={{ fontWeight: 600 }}>{stage.label}</strong>
            {stage.detail ? <small style={{ display: "block" }}>{stage.detail}</small> : null}
          </span>
        </div>
      ))}
      {status === "failed" ? (
        <div className="job-stage failed">
          <span aria-hidden="true">!</span>
          <span>
            {failureReason ?? "任务失败，可重试。"}
            {onRetry ? <button type="button" className="btn sm" style={{ marginLeft: 8 }} onClick={onRetry}>重试</button> : null}
          </span>
        </div>
      ) : null}
    </div>
  );
}
