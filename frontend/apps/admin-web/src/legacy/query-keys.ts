export * from "../../../../packages/query-keys/src/index";

const key = (scope: string, name: string, params?: unknown) => [scope, name, ...(params ? [params] : [])] as const;

export const accountKeys = {
  users: (filters?: object) => key("accounts", "users", filters),
  teachers: (filters?: object) => key("accounts", "teachers", filters),
  admins: (filters?: object) => key("accounts", "admins", filters),
  verifications: (filters?: object) => key("accounts", "verifications", filters),
};
export const courseKeys = { catalog: (filters?: object) => key("courses", "catalog", filters) };
export const governanceKeys = {
  runtimes: () => key("governance", "runtimes"), images: () => key("governance", "images"),
  profiles: () => key("governance", "profiles"), quotas: () => key("governance", "quotas"),
  policies: (kind?: string) => key("governance", "policies", kind), allowlists: () => key("governance", "allowlists"),
  usage: () => key("governance", "usage"), alerts: () => key("governance", "alerts"),
};
export const experimentKeys = { anomalies: () => key("experiments", "anomalies") };
export const workspaceKeys = { adminSessions: () => key("workspaces", "admin-sessions") };
export const reportKeys = { scanAnomalies: () => key("reports", "scan-anomalies") };
export const reviewKeys = { monitor: () => key("reviews", "monitor") };
export const archiveKeys = {
  all: ["archives"] as const,
  instances: () => key("archives", "instances"),
  compensations: (status?: string) => key("archives", "compensations", status),
};
export const agentKeys = { all: ["agents"] as const, platformPolicies: () => key("agents", "platform-policies") };
export const analyticsKeys = { all: ["analytics"] as const, projections: () => key("analytics", "projections") };
export const notificationKeys = {
  list: (portal?: string) => key("notifications", "list", portal),
  preference: (portal?: string) => key("notifications", "preference", portal),
};
export const integrationKeys = {
  providers: () => key("integrations", "providers"), clients: () => key("integrations", "clients"),
  deliveries: () => key("integrations", "deliveries"),
};
export const templateKeys = { platformSummary: () => key("templates", "platform-summary") };
