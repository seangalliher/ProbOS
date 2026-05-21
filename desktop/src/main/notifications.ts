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
