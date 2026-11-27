"use client";

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { ApiError } from "@/lib/api/client";
import { api } from "@/lib/api/endpoints";

/** Deletes the signed-in account after the person types its email, then signs out. */
export function DeleteAccountDialog({
  email,
  open,
  onOpenChange,
}: {
  email: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [typed, setTyped] = useState("");
  const remove = useMutation({
    mutationFn: () => api.deleteAccount(typed),
    onSuccess: async () => {
      // The session row is gone with the account; this clears the cookie and goes home.
      await fetch("/api/auth/signout", { method: "POST" }).catch(() => undefined);
      // A full load on purpose: every cached query belonged to the deleted account.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.assign("/");
    },
  });
  const matches = typed.trim().toLowerCase() === email.toLowerCase();

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) setTyped("");
        onOpenChange(next);
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete your account?</DialogTitle>
          <DialogDescription>
            This permanently deletes your profile, resume data, saved answers, searches and every prepared application.
            It cannot be undone.
          </DialogDescription>
        </DialogHeader>
        <form
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (matches) remove.mutate();
          }}
        >
          <label className="block text-sm text-text-2" htmlFor="confirm-email">
            Type <span className="font-medium text-text-1">{email}</span> to confirm.
          </label>
          <Input
            id="confirm-email"
            type="email"
            autoComplete="off"
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
          />
          {remove.error ? (
            <p role="alert" className="text-sm text-danger">
              {remove.error instanceof ApiError ? remove.error.message : "The account could not be deleted."}
            </p>
          ) : null}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={remove.isPending}>
              Keep my account
            </Button>
            <Button type="submit" variant="destructive" disabled={!matches || remove.isPending}>
              {remove.isPending ? "Deleting…" : "Delete account"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
