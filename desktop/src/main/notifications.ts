/**
 * AD-759 notification wrapper.
 *
 * Wraps Electron's `Notification` API. When a `route` is provided, clicking
 * the notification activates the main window and routes there via the
 * caller-provided activator.
 */

import { Notification } from "electron";
import { logInfo, logWarn } from "./logger.js";

export interface NotifyArgs {
  title: string;
  body: string;
  route?: string;
}

export interface NotifyActivator {
  showAndRoute(route: string): void;
}

export function notify(args: NotifyArgs, activator: NotifyActivator): void {
  if (!Notification.isSupported()) {
    logWarn("notification suppressed; OS notifications not supported", {
      title: args.title,
    });
    return;
  }

  const n = new Notification({ title: args.title, body: args.body });

  if (args.route) {
    const route = args.route;
    n.on("click", () => {
      logInfo("notification clicked; routing", { route });
      activator.showAndRoute(route);
    });
  }

  n.show();
}

/**
 * AD-847: validate an untrusted renderer-supplied task-completion payload.
 *
 * The renderer reaches the main process across the context-isolation
 * boundary, so the payload is untrusted: coerce it into a `NotifyArgs` or
 * return `null` when the required fields are missing/ill-typed. A blank
 * `route` is dropped so a click never routes to an empty path.
 */
export function coerceTaskDonePayload(payload: unknown): NotifyArgs | null {
  if (!payload || typeof payload !== "object") {
    return null;
  }
  const p = payload as Record<string, unknown>;
  if (typeof p.title !== "string" || p.title.length === 0) {
    return null;
  }
  if (typeof p.body !== "string") {
    return null;
  }
  const route =
    typeof p.route === "string" && p.route.length > 0 ? p.route : undefined;
  return { title: p.title, body: p.body, route };
}
