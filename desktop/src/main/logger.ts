/**
 * AD-759 structured logger for the Electron main process.
 *
 * Thin wrapper around console; centralized so every log line carries the
 * `AD-759:` prefix and a level. Per `.github/copilot-instructions.md`
 * logging standards: include what failed, why it matters, what happens next.
 */

export type LogLevel = "info" | "warn" | "error";

export interface LogContext {
  [key: string]: string | number | boolean | null | undefined;
}

function format(level: LogLevel, msg: string, ctx?: LogContext): string {
  const time = new Date().toISOString();
  const ctxStr = ctx
    ? " " +
      Object.entries(ctx)
        .map(([k, v]) => `${k}=${String(v)}`)
        .join(" ")
    : "";
  return `[${time}] [${level.toUpperCase()}] AD-759: ${msg}${ctxStr}`;
}

export function logInfo(msg: string, ctx?: LogContext): void {
  // eslint-disable-next-line no-console
  console.log(format("info", msg, ctx));
}

export function logWarn(msg: string, ctx?: LogContext): void {
  // eslint-disable-next-line no-console
  console.warn(format("warn", msg, ctx));
}

export function logError(msg: string, ctx?: LogContext): void {
  // eslint-disable-next-line no-console
  console.error(format("error", msg, ctx));
}
