/**
 * 业务资源类型（对齐 docs/frontend/frontend-backend-integration-guide.md 第 7 章）。
 * 生成类型可用后（npm run generate:api），这里以本地宽松结构承载，最终以 schema 为准校验。
 */
/** 任务操作常量 */
export const TASK_ACTION = {
    START: "start",
    ENTER: "enter",
    RETRY: "retry",
    COMPLETE: "complete",
    EXTENSION: "extension",
    SUBMIT_REPORT: "submit_report",
    VIEW_WORKBENCH: "view_workbench",
};
export const PUBLICATION_ACTION = {
    PUBLISH: "publish",
    WITHDRAW: "withdraw",
    CLOSE: "close",
    PRECHECK: "precheck",
};
