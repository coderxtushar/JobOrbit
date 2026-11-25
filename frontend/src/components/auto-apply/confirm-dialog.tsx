"use client";

import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

/**
 * A confirm step for actions with consequences. The description says plainly what will
 * happen; the confirm button repeats it, so nobody confirms "OK" without reading.
 */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  confirmLabel,
  tone = "default",
  pending,
  confirmDisabled,
  onConfirm,
  icon,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: React.ReactNode;
  children?: React.ReactNode;
  confirmLabel: string;
  tone?: "default" | "danger" | "warning";
  pending?: boolean;
  confirmDisabled?: boolean;
  onConfirm: () => void;
  icon?: React.ReactNode;
}) {
  return (
    <Dialog open={open} onOpenChange={(next) => (pending ? undefined : onOpenChange(next))}>
      <DialogContent className="gap-5 border border-line-strong bg-surface-1 p-5 shadow-raised sm:max-w-md">
        <DialogHeader className="gap-3">
          <div className="flex items-start gap-3">
            {icon ? (
              <span
                className={cn(
                  "grid size-9 shrink-0 place-items-center rounded-lg ring-1 ring-inset",
                  tone === "danger" && "bg-danger-soft text-danger ring-danger/25",
                  tone === "warning" && "bg-warning-soft text-warning ring-warning/25",
                  tone === "default" && "bg-violet-soft text-violet ring-violet/25",
                )}
              >
                {icon}
              </span>
            ) : null}
            <div className="min-w-0 space-y-1.5">
              <DialogTitle className="text-[15px] font-semibold text-text-1">{title}</DialogTitle>
              <DialogDescription className="text-[13px] leading-relaxed text-text-2">
                {description}
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>
        {children}
        <DialogFooter className="-mx-5 -mb-5 border-line bg-surface-2/60 px-5 py-3.5">
          <DialogClose asChild>
            <Button variant="outline" disabled={pending}>
              Cancel
            </Button>
          </DialogClose>
          <Button
            variant={tone === "default" ? "default" : "destructive"}
            className={cn(
              tone === "danger" && "bg-danger text-white hover:bg-danger/90 dark:bg-danger dark:hover:bg-danger/90",
              tone === "warning" && "bg-warning text-surface-0 hover:bg-warning/90 dark:bg-warning dark:hover:bg-warning/90",
            )}
            disabled={pending || confirmDisabled}
            onClick={onConfirm}
          >
            {pending ? <Loader2 className="animate-spin" /> : null}
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
