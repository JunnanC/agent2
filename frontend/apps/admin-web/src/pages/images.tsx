import { useMutation, useQuery } from "@tanstack/react-query";
import { platformApi } from "@edu/api-client";
import type { ImageScanReportInput, PlatformImage } from "@edu/api-client";
import { keys } from "@edu/query-keys";
import {
  Breadcrumbs, Button, ConfirmDialog, Metric, Modal, Panel, RequestStateView, StatusBadge, useToast,
} from "@edu/ui";
import { useEffect, useState } from "react";
import { apiErrorMessage } from "@/lib/format";
import { useRecentAuthGuard } from "@/lib/recent-auth";

type RiskLevel = "LOW" | "MEDIUM" | "HIGH";

const RISK_LABEL: Record<string, string> = {
  LOW: "低风险",
  MEDIUM: "中风险",
  HIGH: "高风险",
};

const SCAN_LABEL: Record<string, string> = {
  PENDING: "待扫描",
  CLEAN: "扫描干净",
  INFECTED: "检出风险",
  FAILED: "扫描失败",
};

const APPROVAL_LABEL: Record<string, string> = {
  PENDING: "待审批",
  APPROVED: "已批准",
  REJECTED: "已拒绝",
  RETIRED: "已下架",
};

const DIGEST_PATTERN = /sha256:[0-9a-f]{64}$/;
const TAG_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;

const imagesPollIntervalMs = 3000;
const imagesPollDeadlineMs = 120_000;

interface ParsedReference {
  registry: string;
  repository: string;
  tag: string;
  digest: string;
}

/* 支持粘贴 ubuntu:22.04 / org/repo:tag / registry.example.com/org/repo:tag，可带 @sha256: 摘要 */
function parseImageReference(raw: string): ParsedReference | null {
  const value = raw.trim().replace(/^https?:\/\//i, "");
  if (!value) return null;
  let digest = "";
  let main = value;
  const at = value.indexOf("@");
  if (at > 0) {
    digest = value.slice(at + 1);
    main = value.slice(0, at);
  }
  let registry = "docker.io";
  let rest = main;
  const slash = main.indexOf("/");
  if (slash > 0) {
    const head = main.slice(0, slash);
    if (head.includes(".") || head.includes(":") || head === "localhost") {
      registry = head;
      rest = main.slice(slash + 1);
    } else {
      // org/repo 形式：registry 仍是 docker.io，head 属于 repository 命名空间
      rest = main;
    }
  }
  let tag = "latest";
  let repository = rest;
  const colon = rest.lastIndexOf(":");
  if (colon > -1 && colon > rest.lastIndexOf("/")) {
    const candidate = rest.slice(colon + 1);
    if (TAG_PATTERN.test(candidate)) {
      tag = candidate;
      repository = rest.slice(0, colon);
    }
  }
  if (!repository) return null;
  return { registry, repository, tag, digest: DIGEST_PATTERN.test(digest) ? digest : "" };
}

interface AddFormState {
  quick: string;
  registry: string;
  repository: string;
  tag: string;
  digest: string;
  riskLevel: RiskLevel;
  reason: string;
}

const EMPTY_ADD_FORM: AddFormState = {
  quick: "",
  registry: "",
  repository: "",
  tag: "",
  digest: "",
  riskLevel: "LOW",
  reason: "",
};

function riskTone(risk?: string): "good" | "warn" | "bad" | "neutral" {
  if (risk === "LOW") return "good";
  if (risk === "MEDIUM") return "warn";
  if (risk === "HIGH") return "bad";
  return "neutral";
}

interface ScanFormState {
  scanStatus: string;
  reportRef: string;
  risk: RiskLevel;
  reason: string;
}

export function Images() {
  const toast = useToast();
  const recentAuth = useRecentAuthGuard();
  const [showAdd, setShowAdd] = useState(false);
  const [addForm, setAddForm] = useState<AddFormState>(EMPTY_ADD_FORM);
  const [scanTarget, setScanTarget] = useState<PlatformImage | null>(null);
  const [scanForm, setScanForm] = useState<ScanFormState>({ scanStatus: "CLEAN", reportRef: "", risk: "LOW", reason: "" });
  const [decideTarget, setDecideTarget] = useState<{ image: PlatformImage; decision: "approve" | "reject" } | null>(null);
  const [pendingResolveId, setPendingResolveId] = useState<string | null>(null);
  const [pendingReresolve, setPendingReresolve] = useState<{ id: string; digest: string; startedAt: number } | null>(null);

  const images = useQuery({ queryKey: keys.images({}), queryFn: () => platformApi.images({ page_size: 100 }) });
  const rows = images.data?.rows ?? [];

  const refresh = () => void images.refetch();

  const addImage = useMutation({
    mutationFn: () =>
      platformApi.createImage({
        registry: addForm.registry,
        repository: addForm.repository,
        display_tag: addForm.tag || undefined,
        digest: addForm.digest.trim() || undefined,
        risk_level: addForm.riskLevel,
        reason: addForm.reason,
      }),
    onSuccess: () => {
      toast.notify("镜像已加入目录，等待解析 digest 与扫描");
      setAddForm(EMPTY_ADD_FORM);
      setShowAdd(false);
      refresh();
    },
    onError: (error) => {
      if (!recentAuth.intercept(error, () => addImage.mutate())) {
        toast.notify(apiErrorMessage(error), "error");
      }
    },
  });

  const resolveDigest = useMutation({
    mutationFn: (target: PlatformImage) => platformApi.resolveImage(target.public_id, target.row_version),
    onSuccess: (_data, target) => {
      toast.notify("已提交解析任务，运行时正在拉取镜像并计算 sha256，首次可能较久");
      setPendingResolveId(target.public_id);
      refresh();
    },
    onError: (error, target) => {
      if (!recentAuth.intercept(error, () => resolveDigest.mutate(target))) {
        toast.notify(apiErrorMessage(error), "error");
      }
      refresh();
    },
  });

  const pendingRow = pendingResolveId ? rows.find((image) => image.public_id === pendingResolveId) : undefined;
  const pendingResolved = pendingRow?.digest != null;
  const pendingRejected = pendingRow?.approval_status === "REJECTED";

  useEffect(() => {
    if (!pendingResolveId) return;
    if (pendingResolved) {
      toast.notify("已解析出镜像 sha256 摘要，可进行扫描上报");
      setPendingResolveId(null);
      return;
    }
    if (pendingRejected) {
      toast.notify("解析完成：该镜像内容与目录中已批准的镜像相同，已自动拒绝此重复项", "error");
      setPendingResolveId(null);
      return;
    }
    const startedAt = Date.now();
    const timer = window.setInterval(() => {
      void images.refetch();
      if (Date.now() - startedAt > imagesPollDeadlineMs) {
        toast.notify("解析任务仍在进行，请稍后刷新查看结果或重新解析", "error");
        setPendingResolveId(null);
      }
    }, imagesPollIntervalMs);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingResolveId, pendingResolved, pendingRejected]);

  const reResolve = useMutation({
    mutationFn: (target: PlatformImage) => platformApi.reResolveImage(target.public_id, target.row_version),
    onSuccess: (_data, target) => {
      toast.notify("已提交重新解析任务：摘要变化时扫描与审批会失效，请稍后重新扫描并批准");
      setPendingReresolve({ id: target.public_id, digest: target.digest ?? "", startedAt: Date.now() });
      refresh();
    },
    onError: (error, target) => {
      if (!recentAuth.intercept(error, () => reResolve.mutate(target))) {
        toast.notify(apiErrorMessage(error), "error");
      }
      refresh();
    },
  });

  useEffect(() => {
    if (!pendingReresolve) return;
    const row = rows.find((image) => image.public_id === pendingReresolve.id);
    if (row && pendingReresolve.digest && row.digest !== pendingReresolve.digest) {
      toast.notify("运行时摘要已更新：此前扫描与批准已失效，请重新扫描并批准", "error");
      setPendingReresolve(null);
      return;
    }
    const timer = window.setInterval(() => {
      void images.refetch();
      if (Date.now() - pendingReresolve.startedAt > imagesPollDeadlineMs) {
        toast.notify("重新解析任务仍在进行或摘要未变化，请稍后刷新确认", "error");
        setPendingReresolve(null);
      }
    }, imagesPollIntervalMs);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingReresolve, rows]);

  const reportScan = useMutation({
    mutationFn: (input: { target: PlatformImage; form: ScanFormState }) =>
      platformApi.reportImageScan(
        input.target.public_id,
        {
          scan_status: input.form.scanStatus as ImageScanReportInput["scan_status"],
          ...(input.form.reportRef.trim() ? { scan_report_ref: input.form.reportRef.trim() } : {}),
          risk_level: input.form.risk,
          reason: input.form.reason,
        },
        input.target.row_version,
      ),
    onSuccess: () => {
      toast.notify("扫描结果已登记");
      setScanTarget(null);
      refresh();
    },
    onError: (error, input) => {
      if (!recentAuth.intercept(error, () => reportScan.mutate(input))) {
        toast.notify(apiErrorMessage(error), "error");
      }
      refresh();
    },
  });

  const decide = useMutation({
    mutationFn: (input: { target: PlatformImage; decision: "approve" | "reject" }) =>
      platformApi.decideImage(input.target.public_id, { decision: input.decision }, input.target.row_version),
    onSuccess: (_data, input) => {
      toast.notify(input.decision === "approve" ? "镜像已批准，教师端可选用" : "已拒绝镜像");
      setDecideTarget(null);
      refresh();
    },
    onError: (error, input) => {
      if (!recentAuth.intercept(error, () => decide.mutate(input))) {
        toast.notify(apiErrorMessage(error), "error");
      }
      refresh();
    },
  });

  const approvedCount = rows.filter((image) => image.approval_status === "APPROVED").length;
  const pendingCount = rows.filter((image) => image.approval_status === "PENDING").length;
  const unresolvedCount = rows.filter((image) => !image.digest).length;

  const applyQuickReference = () => {
    const parsed = parseImageReference(addForm.quick);
    if (!parsed) return;
    setAddForm({
      ...EMPTY_ADD_FORM,
      quick: addForm.quick,
      registry: parsed.registry,
      repository: parsed.repository,
      tag: parsed.tag,
      digest: parsed.digest,
      riskLevel: addForm.riskLevel,
      reason: addForm.reason,
    });
  };

  const canAdd = addForm.registry.trim().length > 0
    && addForm.repository.trim().length > 0
    && addForm.reason.trim().length > 0
    && (!addForm.digest.trim() || DIGEST_PATTERN.test(addForm.digest.trim()));

  const imageLabel = (image: PlatformImage) => {
    const name = image.repository || image.public_id;
    return image.display_tag ? `${name} : ${image.display_tag}` : name;
  };

  return (
    <>
      <Breadcrumbs items={[{ label: "平台管理" }, { label: "资源治理" }]} current="镜像目录" />
      <div className="page-actions align-end">
        <Button onClick={refresh} ariaLabel="刷新镜像列表">刷新</Button>
        <Button variant="primary" onClick={() => { setAddForm(EMPTY_ADD_FORM); setShowAdd(true); }}>
          添加镜像
        </Button>
      </div>

      <Panel className="section">
        <RequestStateView
          loading={images.isLoading}
          error={images.error}
          onRetry={refresh}
          empty={false}
          emptyState={null}
        >
          <div className="metric-strip">
            <Metric label="已批准镜像" value={String(approvedCount)} icon="boxes" sub="教师端可选" />
            <Metric label="待审批" value={String(pendingCount)} icon="gauge" sub="等待扫描与批准" />
            <Metric label="待解析 digest" value={String(unresolvedCount)} icon="monitor" sub="解析后再扫描" />
          </div>
        </RequestStateView>
      </Panel>

      <Panel className="section" title={<><h2>镜像目录</h2><span className="subtle">批准并扫描干净的镜像，教师可在实验模板“运行环境”中选择</span></>}>
        <RequestStateView
          loading={images.isLoading}
          error={images.error}
          onRetry={refresh}
          empty={!rows.length}
          emptyState={
            <div className="state-block">
              <strong>镜像目录为空</strong>
              <p>添加 ubuntu / python / jdk 等常用镜像，批准后供教师创建实验模板使用。</p>
            </div>
          }
        >
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>镜像</th><th>Digest</th><th>风险</th><th>扫描</th><th>审批</th><th>操作</th></tr></thead>
              <tbody>
                {rows.map((image) => {
                  const resolving = pendingResolveId === image.public_id || (resolveDigest.isPending && resolveDigest.variables?.public_id === image.public_id);
                  const unresolved = !image.digest && image.approval_status !== "APPROVED";
                  return (
                    <tr key={image.public_id}>
                      <td>
                        <strong>{imageLabel(image)}</strong>
                        <small style={{ display: "block" }}>{image.registry}</small>
                      </td>
                      <td>
                        <small>{image.digest ? `${image.digest.slice(0, 18)}…` : <span className="subtle">未解析</span>}</small>
                      </td>
                      <td><StatusBadge tone={riskTone(image.risk_level)}>{RISK_LABEL[image.risk_level ?? ""] ?? "—"}</StatusBadge></td>
                      <td>
                        <StatusBadge tone={image.scan_status === "CLEAN" ? "good" : image.scan_status === "INFECTED" ? "bad" : "neutral"}>
                          {SCAN_LABEL[image.scan_status] ?? image.scan_status}
                        </StatusBadge>
                      </td>
                      <td>
                        {image.approval_status === "APPROVED"
                          ? <StatusBadge tone="good">{APPROVAL_LABEL[image.approval_status]}</StatusBadge>
                          : <StatusBadge tone={image.approval_status === "REJECTED" ? "bad" : "neutral"}>{APPROVAL_LABEL[image.approval_status] ?? image.approval_status}</StatusBadge>}
                      </td>
                      <td>
                        <div className="row-actions">
                          {unresolved ? (
                            <Button
                              size="sm"
                              disabled={resolveDigest.isPending || pendingResolveId === image.public_id}
                              onClick={() => resolveDigest.mutate(image)}
                              title={resolving ? "解析任务已在队列中，完成列表自动刷新" : "由平台经运行时拉取镜像并解析 sha256，首次可能较久"}
                              ariaLabel={`解析 ${imageLabel(image)} 的 digest`}
                            >
                              {resolving ? "解析中…" : "解析 digest"}
                            </Button>
                          ) : null}
                          {image.digest && image.approval_status !== "RETIRED" ? (
                            <Button
                              size="sm"
                              disabled={reResolve.isPending || pendingReresolve?.id === image.public_id}
                              onClick={() => reResolve.mutate(image)}
                              title="运行时镜像重建后摘要可能漂移：重新解析会刷新摘要并使扫描/审批失效"
                              ariaLabel={`重新解析 ${imageLabel(image)} 的 digest`}
                            >
                              {pendingReresolve?.id === image.public_id ? "重新解析中…" : "重新解析"}
                            </Button>
                          ) : null}
                          {image.approval_status !== "APPROVED" && image.approval_status !== "RETIRED" ? (
                            <>
                              <Button size="sm" onClick={() => {
                                setScanForm({ scanStatus: "CLEAN", reportRef: "", risk: (image.risk_level as RiskLevel) ?? "LOW", reason: "" });
                                setScanTarget(image);
                              }}>
                                扫描上报
                              </Button>
                              <Button size="sm" variant="primary" disabled={!image.digest} onClick={() => setDecideTarget({ image, decision: "approve" })} title={image.digest ? undefined : "需先解析 digest"}>
                                批准
                              </Button>
                              <Button size="sm" variant="danger" onClick={() => setDecideTarget({ image, decision: "reject" })}>拒绝</Button>
                            </>
                          ) : null}
                          {image.approval_status === "APPROVED" ? <span className="subtle">已上架</span> : null}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </RequestStateView>
      </Panel>

      <Modal
        open={showAdd}
        onClose={() => setShowAdd(false)}
        eyebrow="镜像目录"
        title="添加常用镜像"
        actions={(
          <>
            <Button onClick={() => setShowAdd(false)} disabled={addImage.isPending}>取消</Button>
            <Button variant="primary" disabled={addImage.isPending || !canAdd} onClick={() => addImage.mutate()}>
              {addImage.isPending ? "提交中…" : "加入目录"}
            </Button>
          </>
        )}
      >
        <p className="subtle">加入目录后先“解析 digest”，再“扫描上报”，批准后才对教师可见。</p>
        <label className="form-label" htmlFor="image-quick">快速填写 <span>粘贴完整镜像名自动拆解</span></label>
        <div style={{ display: "flex", gap: 8 }}>
          <input
            id="image-quick"
            className="field"
            style={{ flex: 1 }}
            placeholder="如 ubuntu:22.04 或 registry.example.com/lab/jdk:17"
            value={addForm.quick}
            onChange={(event) => setAddForm((base) => ({ ...base, quick: event.target.value }))}
            onBlur={applyQuickReference}
          />
        </div>
        <label className="form-label" htmlFor="image-registry">Registry</label>
        <input
          id="image-registry"
          className="field"
          placeholder="docker.io"
          value={addForm.registry}
          onChange={(event) => setAddForm((base) => ({ ...base, registry: event.target.value }))}
        />
        <label className="form-label" htmlFor="image-repository">Repository</label>
        <input
          id="image-repository"
          className="field"
          placeholder="library/ubuntu"
          value={addForm.repository}
          onChange={(event) => setAddForm((base) => ({ ...base, repository: event.target.value }))}
        />
        <label className="form-label" htmlFor="image-tag">标签（Tag）</label>
        <input
          id="image-tag"
          className="field"
          placeholder="22.04，留空按 latest 解析"
          value={addForm.tag}
          onChange={(event) => setAddForm((base) => ({ ...base, tag: event.target.value }))}
        />
        <label className="form-label" htmlFor="image-digest">Digest <span>选填，可留空由平台解析</span></label>
        <input
          id="image-digest"
          className="field"
          placeholder="sha256:…（选填）"
          value={addForm.digest}
          onChange={(event) => setAddForm((base) => ({ ...base, digest: event.target.value }))}
        />
        {!addForm.digest.trim() || DIGEST_PATTERN.test(addForm.digest.trim()) ? null : (
          <p className="subtle" style={{ color: "var(--danger, #c0392b)" }}>Digest 需形如 sha256:64 位十六进制，或留空由平台解析。</p>
        )}
        <label className="form-label" htmlFor="image-risk">风险等级</label>
        <select
          id="image-risk"
          className="field"
          value={addForm.riskLevel}
          onChange={(event) => setAddForm((base) => ({ ...base, riskLevel: event.target.value as RiskLevel }))}
        >
          <option value="LOW">低风险</option>
          <option value="MEDIUM">中风险</option>
          <option value="HIGH">高风险</option>
        </select>
        <label className="form-label" htmlFor="image-reason">变更原因</label>
        <textarea
          id="image-reason"
          className="field"
          rows={2}
          placeholder="例如：基础课程需要 ubuntu 环境"
          value={addForm.reason}
          onChange={(event) => setAddForm((base) => ({ ...base, reason: event.target.value }))}
        />
      </Modal>

      <Modal
        open={scanTarget != null}
        onClose={() => setScanTarget(null)}
        eyebrow="镜像治理"
        title="上报扫描结果"
        actions={(
          <>
            <Button onClick={() => setScanTarget(null)} disabled={reportScan.isPending}>取消</Button>
            <Button variant="primary" disabled={reportScan.isPending || scanForm.reason.trim().length === 0}
              onClick={() => { if (scanTarget) reportScan.mutate({ target: scanTarget, form: scanForm }); }}>
              {reportScan.isPending ? "提交中…" : "登记结果"}
            </Button>
          </>
        )}
      >
        <p className="subtle">批准镜像要求扫描结果为 CLEAN；INFECTED / FAILED 的镜像不能批准。</p>
        <label className="form-label" htmlFor="scan-status">扫描结论</label>
        <select
          id="scan-status"
          className="field"
          value={scanForm.scanStatus}
          onChange={(event) => setScanForm((base) => ({ ...base, scanStatus: event.target.value }))}
        >
          <option value="CLEAN">扫描干净（CLEAN）</option>
          <option value="INFECTED">检出风险（INFECTED）</option>
          <option value="FAILED">扫描失败（FAILED）</option>
        </select>
        <label className="form-label" htmlFor="scan-ref">扫描报告引用 <span>选填</span></label>
        <input
          id="scan-ref"
          className="field"
          placeholder="如 scanner/run-2026-10"
          value={scanForm.reportRef}
          onChange={(event) => setScanForm((base) => ({ ...base, reportRef: event.target.value }))}
        />
        <label className="form-label" htmlFor="scan-risk">风险等级</label>
        <select
          id="scan-risk"
          className="field"
          value={scanForm.risk}
          onChange={(event) => setScanForm((base) => ({ ...base, risk: event.target.value as RiskLevel }))}
        >
          <option value="LOW">低风险</option>
          <option value="MEDIUM">中风险</option>
          <option value="HIGH">高风险</option>
        </select>
        <label className="form-label" htmlFor="scan-reason">变更原因</label>
        <textarea
          id="scan-reason"
          className="field"
          rows={2}
          placeholder="例如：已按扫描流程出具报告"
          value={scanForm.reason}
          onChange={(event) => setScanForm((base) => ({ ...base, reason: event.target.value }))}
        />
      </Modal>

      <ConfirmDialog
        open={decideTarget != null}
        onClose={() => setDecideTarget(null)}
        onConfirm={() => { if (decideTarget) decide.mutate({ target: decideTarget.image, decision: decideTarget.decision }); }}
        tone={decideTarget?.decision === "approve" ? "primary" : "danger"}
        busy={decide.isPending}
        title={decideTarget?.decision === "approve" ? "批准镜像？" : "拒绝镜像？"}
        eyebrow="镜像治理"
        confirmLabel={decideTarget?.decision === "approve" ? "批准" : "拒绝"}
        description={decideTarget?.decision === "approve"
          ? <p>批准并保持扫描 CLEAN 后，教师可在实验模板中选择该镜像。</p>
          : <p>拒绝后该镜像不可被教师使用，之后仍可重新走扫描与批准流程。</p>}
      />

      {recentAuth.dialog}
    </>
  );
}