export * from "../../../../packages/query-keys/src/index";
const key = (scope, name, params) => [scope, name, ...(params ? [params] : [])];
export const accountKeys = {
    users: (filters) => key("accounts", "users", filters),
    teachers: (filters) => key("accounts", "teachers", filters),
    admins: (filters) => key("accounts", "admins", filters),
    verifications: (filters) => key("accounts", "verifications", filters),
};
export const courseKeys = { catalog: (filters) => key("courses", "catalog", filters) };
export const governanceKeys = {
    runtimes: () => key("governance", "runtimes"), images: () => key("governance", "images"),
    profiles: () => key("governance", "profiles"), quotas: () => key("governance", "quotas"),
    policies: (kind) => key("governance", "policies", kind), allowlists: () => key("governance", "allowlists"),
    usage: () => key("governance", "usage"), alerts: () => key("governance", "alerts"),
};
export const experimentKeys = { anomalies: () => key("experiments", "anomalies") };
export const workspaceKeys = { adminSessions: () => key("workspaces", "admin-sessions") };
export const reportKeys = { scanAnomalies: () => key("reports", "scan-anomalies") };
export const reviewKeys = { monitor: () => key("reviews", "monitor") };
export const archiveKeys = {
    all: ["archives"],
    instances: () => key("archives", "instances"),
    compensations: (status) => key("archives", "compensations", status),
};
export const agentKeys = { all: ["agents"], platformPolicies: () => key("agents", "platform-policies") };
export const analyticsKeys = { all: ["analytics"], projections: () => key("analytics", "projections") };
export const notificationKeys = {
    list: (portal) => key("notifications", "list", portal),
    preference: (portal) => key("notifications", "preference", portal),
};
export const integrationKeys = {
    providers: () => key("integrations", "providers"), clients: () => key("integrations", "clients"),
    deliveries: () => key("integrations", "deliveries"),
};
export const templateKeys = { platformSummary: () => key("templates", "platform-summary") };
