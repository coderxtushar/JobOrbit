"use client";

import { AlertTriangle, PlugZap, RotateCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api/client";
import { cn } from "@/lib/utils";

/** The backend's own error message, with a fix when the API is simply not running. */
export function ErrorState({
  error,
  onRetry,
  className,
}: {
  error: unknown;
  onRetry?: () => void;
  className?: string;
}) {
  const apiError = error instanceof ApiError ? error : null;
  const unreachable = apiError?.isUnreachable ?? false;
  const Icon = unreachable ? PlugZap : AlertTriangle;
  return (
    <div
      role="alert"
      className={cn(
        "flex flex-col gap-3 rounded-xl border border-danger/25 bg-danger-soft p-4 sm:flex-row sm:items-start",
        className,
      )}
    >
      <Icon className="mt-0.5 size-4 shrink-0 text-danger" />
      <div className="min-w-0 flex-1 space-y-1">
        <p className="text-sm font-medium text-text-1">
          {unreachable ? "The JobOrbit API is not running" : "This could not be loaded"}
        </p>
        <p className="break-words text-xs leading-relaxed text-text-2">
          {apiError?.message ?? (error as Error)?.message ?? "Unknown error"}
        </p>
      </div>
      {onRetry ? (
        <Button size="sm" variant="outline" onClick={onRetry}>
          <RotateCw /> Retry
        </Button>
      ) : null}
    </div>
  );
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Something went wrong";
}
