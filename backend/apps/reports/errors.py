from apps.core.errors import CoreError


class ReportStateConflict(CoreError):
    code = "REPORT_STATE_CONFLICT"
    message = "报告当前状态不允许此操作"
    status_code = 409


class ReportSnapshotConflict(CoreError):
    code = "REPORT_SNAPSHOT_CONFLICT"
    message = "工作区内容已变化，请保存草稿后重试"
    status_code = 412


class ReportExecutionNotReady(CoreError):
    code = "REPORT_EXECUTION_NOT_READY"
    message = "提交报告前必须完成当前工作区快照的执行"
    status_code = 409


class ReportExecutionConflict(CoreError):
    code = "REPORT_EXECUTION_CONFLICT"
    message = "执行结果与报告快照不匹配"
    status_code = 412


class ReportAttachmentNotReady(CoreError):
    code = "REPORT_ATTACHMENT_NOT_READY"
    message = "附件尚未通过安全扫描"
    status_code = 409


class ReportUploadInvalid(CoreError):
    code = "REPORT_UPLOAD_INVALID"
    message = "报告附件无效"
    status_code = 422


class ReportScanUnavailable(CoreError):
    code = "REPORT_SCAN_UNAVAILABLE"
    message = "文件安全扫描暂时不可用"
    status_code = 503
    retryable = True
