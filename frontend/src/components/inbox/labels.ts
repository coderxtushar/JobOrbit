import type { Tone } from "@/lib/constants/states";

/** Where a saved or prepared answer came from. Mirrors AnswerProvenance in the backend. */
export const PROVENANCE: Record<string, { label: string; tone: Tone; hint: string }> = {
  user_entered: {
    label: "Typed by you",
    tone: "success",
    hint: "You entered this answer yourself. Reusing it applies your own words again.",
  },
  profile_verified: {
    label: "Verified profile",
    tone: "cyan",
    hint: "Read from a field you filled in on your profile.",
  },
  resume_extracted: {
    label: "From resume",
    tone: "neutral",
    hint: "Extracted from your uploaded resume.",
  },
  ai_draft: {
    label: "AI draft",
    tone: "violet",
    hint: "Generated text. Drafts are never stored in the answer bank.",
  },
  needs_user_input: {
    label: "Needs your input",
    tone: "warning",
    hint: "No verified answer exists yet.",
  },
};

/** Shown when the application detail could not supply the backend's own flag reason. */
export function fallbackReason(sensitive: boolean): string {
  return sensitive
    ? "This question is sensitive or legal in nature (salary, notice period, work authorisation, declarations and similar). Your profile has no verified value for it, and JobOrbit never drafts an answer to it for you."
    : "Your profile has no verified value for this question, so it is left for you rather than guessed.";
}
