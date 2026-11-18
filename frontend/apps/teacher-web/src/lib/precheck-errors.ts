import type { PrecheckRun } from "@edu/api-client";

const detailMessages: Record<string, string> = {
  programming_runtime_required: "请在「编程题运行环境」选择运行适配器、执行镜像和资源规格，然后保存。",
  stdio_requires_docker_local: "编程题需要使用 Docker Local 运行适配器。",
  approved_image_and_enabled_runtime_required: "请选择已审批的执行镜像和已启用的运行适配器。",
  real_reference_execution_required: "当前环境未启用实际判题，无法运行参考解。请联系管理员。",
  toolchain_smoke_failed: "执行镜像未通过编程语言工具链检查。请核对镜像是否支持题目允许的语言。",
  reference_does_not_pass_samples: "参考解未通过公开示例。请核对「公开示例」的输入、预期输出和参考解代码。",
  reference_does_not_pass_all_hidden_tests: "参考解未通过全部隐藏用例。请核对隐藏输入、预期输出和参考解代码。",
  exceeds_resource_profile: "题目的内存限制超过了资源规格上限。请调整题目内存限制或选择其他资源规格。",
  supported_unique_languages_required: "请为编程题选择至少一种受支持的允许语言。",
  allowed_language_reference_required: "请提供参考解，且参考解语言必须属于允许语言。",
  "starter_files.default_entrypoint_required": "初始文件缺少对应编程语言的入口文件。",
  "reference_solutions.default_entrypoint_required": "参考解缺少对应编程语言的入口文件。",
  language_configuration_required: "编程题缺少初始文件或运行限制配置。",
  configuration_required_for_each_language: "每种允许语言都需要配置初始文件和运行限制。",
  positive_resource_limits_required: "请检查编程题的超时和内存限制是否在允许范围内。",
  "questions.at_least_one_required": "请添加至少一道题目。",
  "samples.at_least_one_required": "请添加至少一个公开示例。",
  "groups.at_least_one_required": "请添加至少一个隐藏测试组。",
  each_chapter_requires_questions: "每个题目分组至少需要一道题目。",
  input_output_text_required: "请检查公开示例的输入、输出格式和长度。",
  score_sum_mismatch: "隐藏测试组的分值之和与题目总分不一致。",
  unique_group_ids_required: "隐藏测试组的编号必须有效且互不重复。",
  asset_id_required: "隐藏测试用例尚未保存，请重新保存题目。",
  clean_owned_tests_required: "隐藏测试用例不可用，请重新保存题目。",
  groups_required: "隐藏测试文件缺少测试组。请检查文件格式。",
  group_set_mismatch: "隐藏测试文件中的测试组与题目里的测试组不一致。",
  invalid_group: "隐藏测试组格式有误，或组内没有用例。",
  invalid_case: "隐藏用例的输入或输出格式有误，或超过长度限制。",
  invalid_json: "隐藏测试文件的 JSON 格式有误。",
  digest_mismatch: "隐藏测试文件校验失败，请重新保存题目。",
  "tests.too_large": "隐藏测试文件超过大小限制。",
  too_many_cases: "隐藏测试用例数量超过限制。",
  two_to_six_required: "选择题需要填写 2 到 6 个选项。",
  unique_ids_and_nonempty_text_required: "请填写所有选项，并确认选项没有重复。",
  invalid_answer_set: "请检查选择题是否已选中正确答案，且答案数量符合题型要求。",
  mixed_legacy_and_assessment_questions: "模板包含旧版题型，请检查并更新题目。",
  "spec_digest.duplicate": "同一模板已有内容相同的版本。请使用已有版本，或修改当前版本后重新预检。",
};

const codeMessages: Record<string, string> = {
  PRECHECK_WORKER_FAILED: "预检服务执行失败，请重新预检。",
  PRECHECK_MAX_ATTEMPTS_EXCEEDED: "预检已达到最大重试次数，请重新预检。",
  TEMPLATE_VALIDATION_ERROR: "模板配置校验失败，服务端未返回具体原因。",
  TEMPLATE_ASSET_NOT_READY: "模板附件尚未通过安全校验，请检查附件状态。",
  TEMPLATE_DIGEST_MISMATCH: "当前模板内容与预检记录不一致，请重新预检。",
};

export function precheckFailureMessage({ error_code, error_detail }: Pick<PrecheckRun, "error_code" | "error_detail">): string {
  const details = Object.entries(error_detail ?? {}).flatMap(([field, reason]) => {
    if (typeof reason !== "string") return [];
    const fieldReason = `${field}.${reason}`;
    if (Object.hasOwn(detailMessages, fieldReason)) return [detailMessages[fieldReason]];
    if (Object.hasOwn(detailMessages, reason)) return [detailMessages[reason]];
    if (error_code === "TEMPLATE_VALIDATION_ERROR" && /^[a-z_]+$/.test(field) && /^[a-z_]+$/.test(reason)) {
      return [`字段 ${field} 校验失败（${reason}）。`];
    }
    return [];
  });
  if (details.length) return [...new Set(details)].join("");
  if (error_code && Object.hasOwn(codeMessages, error_code)) return codeMessages[error_code]!;
  if (error_code && /^[A-Z][A-Z0-9_]*$/.test(error_code)) return `服务端返回错误代码 ${error_code}。`;
  return "服务端未返回具体失败原因，请重新预检。";
}
