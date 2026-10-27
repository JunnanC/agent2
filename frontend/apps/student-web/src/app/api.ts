import { meApi } from "@edu/api-client";
import { queryClient } from "./providers";

export { queryClient };
export const meApiFn = meApi.retrieve;
