"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Briefcase,
  FileText,
  GraduationCap,
  Loader2,
  MapPin,
  RotateCcw,
  Save,
  ShieldAlert,
  SlidersHorizontal,
  UserRound,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useState } from "react";
import { FormProvider, useForm, useWatch, type FieldPath, type FieldErrors } from "react-hook-form";
import { toast } from "sonner";

import { PageHeader } from "@/components/shared/page-header";
import { ErrorState } from "@/components/shared/query-state";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ApiError, type Schemas } from "@/lib/api/client";
import { api } from "@/lib/api/endpoints";
import { formatRelative } from "@/lib/formatting";
import { cn } from "@/lib/utils";

import { CompletenessCard } from "./completeness-card";
import type { ProposalSelection } from "./parsed-proposal";
import {
  BackgroundSection,
  CompensationSection,
  ExperienceSection,
  FiltersSection,
  IdentitySection,
  PreferencesSection,
} from "./profile-sections";
import {
  COMPLETENESS,
  FIELD_SECTION,
  SENSITIVE_FIELD_LABELS,
  flattenFieldErrors,
  profileSchema,
  toFormValues,
  toPayload,
  type ProfileFieldName,
  type ProfileFormValues,
  type SectionId,
} from "./profile-schema";
import { ResumePanel } from "./resume-panel";

const FORM_ID = "profile-form";

const SECTIONS: Array<{ id: SectionId; label: string; icon: LucideIcon; title: string; description: string }> = [
  {
    id: "resumes",
    label: "Resumes",
    icon: FileText,
    title: "Resumes",
    description: "Upload, pick the primary one, review what was extracted and build role-specific variants.",
  },
  {
    id: "identity",
    label: "Identity",
    icon: UserRound,
    title: "Identity and links",
    description: "Your name and contact details as employers will see them.",
  },
  {
    id: "experience",
    label: "Experience & skills",
    icon: Briefcase,
    title: "Experience and skills",
    description: "What the matcher compares against every listing.",
  },
  {
    id: "background",
    label: "Education & projects",
    icon: GraduationCap,
    title: "Education, projects and certifications",
    description: "Facts interview prep and resume variants may quote. Nothing is added that is not here or on your resume.",
  },
  {
    id: "preferences",
    label: "Preferences",
    icon: MapPin,
    title: "Preferences",
    description: "Where and how you want to work.",
  },
  {
    id: "compensation",
    label: "Pay & eligibility",
    icon: Wallet,
    title: "Pay, notice and eligibility",
    description: "Sensitive answers. Never guessed, never drafted.",
  },
  {
    id: "filters",
    label: "Filters & limits",
    icon: SlidersHorizontal,
    title: "Filters and hard constraints",
    description: "What is filtered out before a listing is scored or prepared.",
  },
];

const FORM_SECTIONS: Record<Exclude<SectionId, "resumes">, () => React.JSX.Element> = {
  identity: IdentitySection,
  experience: ExperienceSection,
  background: BackgroundSection,
  preferences: PreferencesSection,
  compensation: CompensationSection,
  filters: FiltersSection,
};

function isFormPath(path: string): path is FieldPath<ProfileFormValues> {
  const root = path.split(".")[0];
  return root in FIELD_SECTION;
}

function sectionOfPath(path: string): SectionId | null {
  const root = path.split(".")[0] as ProfileFieldName;
  return FIELD_SECTION[root] ?? null;
}

function unionCaseless(current: string[], incoming: string[]): string[] {
  const seen = new Set(current.map((item) => item.toLowerCase()));
  const next = [...current];
  for (const item of incoming) {
    const trimmed = item.trim();
    if (!trimmed || seen.has(trimmed.toLowerCase())) continue;
    seen.add(trimmed.toLowerCase());
    next.push(trimmed);
  }
  return next;
}

function ProfileSkeleton() {
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <Skeleton className="h-3 w-20" />
        <Skeleton className="h-8 w-72" />
        <Skeleton className="h-4 w-[28rem] max-w-full" />
      </div>
      <div className="grid gap-6 lg:grid-cols-[15rem_minmax(0,1fr)]">
        <div className="space-y-3">
          <Skeleton className="h-36 w-full rounded-xl" />
          {Array.from({ length: 7 }).map((_, index) => (
            <Skeleton key={index} className="h-9 w-full" />
          ))}
        </div>
        <Skeleton className="h-[32rem] w-full rounded-xl" />
      </div>
    </div>
  );
}

export function ProfileView() {
  const profile = useQuery({ queryKey: ["profile"], queryFn: api.profile });
  if (profile.isLoading) return <ProfileSkeleton />;
  if (profile.isError || !profile.data) {
    return (
      <div className="space-y-6">
        <PageHeader eyebrow="Profile" title="Resume and profile" />
        <ErrorState error={profile.error} onRetry={() => profile.refetch()} />
      </div>
    );
  }
  return <ProfileWorkspace key={profile.data.id} profile={profile.data} />;
}

function ProfileWorkspace({ profile }: { profile: Schemas["ProfileRead"] }) {
  const queryClient = useQueryClient();
  const [section, setSection] = useState<SectionId>("resumes");
  const [serverError, setServerError] = useState<{ message: string; details: string[] } | null>(null);

  const form = useForm<ProfileFormValues>({
    resolver: zodResolver(profileSchema),
    defaultValues: toFormValues(profile),
    mode: "onBlur",
    reValidateMode: "onChange",
  });
  const { control, formState } = form;
  const values = useWatch({ control }) as ProfileFormValues;
  const isDirty = formState.isDirty;

  useEffect(() => {
    if (!isDirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [isDirty]);

  const save = useMutation({
    mutationFn: (body: Schemas["ProfileUpdate"]) => api.updateProfile(body),
    onSuccess: (saved) => {
      queryClient.setQueryData(["profile"], saved);
      queryClient.invalidateQueries({ queryKey: ["profile"] });
      form.reset(toFormValues(saved));
      setServerError(null);
      toast.success("Profile saved", {
        description: saved.unanswered_sensitive_fields?.length
          ? "Some sensitive answers are still not stated; forms that ask them will wait for you."
          : undefined,
      });
    },
    onError: (error) => {
      const details: string[] = [];
      let firstSection: SectionId | null = null;
      if (error instanceof ApiError) {
        for (const { path, message } of flattenFieldErrors(error.fieldErrors)) {
          if (isFormPath(path)) {
            form.setError(path, { type: "server", message });
            firstSection ??= sectionOfPath(path);
          } else {
            details.push(path && path !== "body" ? `${path}: ${message}` : message);
          }
        }
      }
      setServerError({ message: error instanceof Error ? error.message : "The profile could not be saved.", details });
      if (firstSection) setSection(firstSection);
      toast.error("The profile was not saved", { description: error instanceof Error ? error.message : undefined });
    },
  });

  const onValid = (data: ProfileFormValues) => {
    const full = toPayload(data);
    const dirty = Object.keys(formState.dirtyFields) as ProfileFieldName[];
    const body: Record<string, unknown> = {};
    for (const key of dirty) {
      if (key in full) body[key] = full[key as keyof typeof full];
    }
    // Keep a salary range consistent: the backend checks min <= max only within one request.
    if ("salary_expectation_min" in body || "salary_expectation_max" in body) {
      body.salary_expectation_min = full.salary_expectation_min;
      body.salary_expectation_max = full.salary_expectation_max;
    }
    if (Object.keys(body).length === 0) return;
    setServerError(null);
    save.mutate(body as Schemas["ProfileUpdate"]);
  };

  const onInvalid = (errors: FieldErrors<ProfileFormValues>) => {
    const first = Object.keys(errors)[0];
    const target = first ? sectionOfPath(first) : null;
    if (target) setSection(target);
    toast.error("Some fields need attention", { description: "They are marked in red." });
  };

  const errorSections = new Set(
    Object.keys(formState.errors)
      .map((key) => sectionOfPath(key))
      .filter(Boolean) as SectionId[],
  );

  const sectionComplete = (id: SectionId) => {
    const items = COMPLETENESS.filter((item) => item.section === id);
    return items.length > 0 && items.every((item) => item.filled(values));
  };

  const applyProposal = (selection: ProposalSelection) => {
    const options = { shouldDirty: true, shouldValidate: true } as const;
    const current = form.getValues();
    let count = 0;
    const setText = (name: "full_name" | "email" | "phone" | "graduation_date" | "years_experience", value: string | undefined) => {
      if (value === undefined) return;
      form.setValue(name, value, options);
      count++;
    };
    const mergeList = (name: "links" | "technical_skills" | "certifications", incoming: string[] | undefined) => {
      if (!incoming) return;
      form.setValue(name, unionCaseless(current[name], incoming), options);
      count++;
    };
    setText("full_name", selection.full_name);
    setText("email", selection.email);
    setText("phone", selection.phone);
    setText("graduation_date", selection.graduation_date);
    setText(
      "years_experience",
      selection.years_experience === undefined ? undefined : String(selection.years_experience),
    );
    mergeList("links", selection.links);
    mergeList("technical_skills", selection.skills);
    mergeList("certifications", selection.certifications);
    if (selection.education) {
      const key = (entry: { degree: string; institution: string }) =>
        `${entry.degree}|${entry.institution}`.toLowerCase().trim();
      const known = new Set(current.education.map(key));
      const added = selection.education.filter((entry) => !known.has(key(entry)));
      form.setValue("education", [...current.education, ...added], options);
      count++;
    }
    if (selection.projects) {
      const known = new Set(current.projects.map((entry) => entry.name.toLowerCase().trim()));
      const added = selection.projects
        .filter((entry) => entry.name.trim() && !known.has(entry.name.toLowerCase().trim()))
        .map((entry) => ({ ...entry, technologies: entry.technologies ?? [] }));
      form.setValue("projects", [...current.projects, ...added], options);
      count++;
    }
    if (!count) return;
    toast.success(`Copied ${count} field${count === 1 ? "" : "s"} into the profile form`, {
      description: "Nothing is saved yet. Review the values, then press Save profile.",
      action: { label: "Review", onClick: () => setSection("identity") },
    });
  };

  const discard = () => {
    form.reset(toFormValues(profile));
    setServerError(null);
  };

  const unanswered = Array.from(
    new Set((profile.unanswered_sensitive_fields ?? []).map((field) => SENSITIVE_FIELD_LABELS[field] ?? field)),
  );
  const active = SECTIONS.find((item) => item.id === section) ?? SECTIONS[0];
  const SaveIcon = save.isPending ? Loader2 : Save;

  return (
    <FormProvider {...form}>
      <div className="space-y-6 pb-20">
        <PageHeader
          eyebrow="Profile"
          title="Resume and profile"
          description="The facts every application is built from. Anything you leave blank stays “not stated” — JobOrbit never fills it in for you."
          actions={
            <>
              <span className="hidden text-xs text-text-3 sm:inline">Saved {formatRelative(profile.updated_at)}</span>
              <Button type="button" variant="outline" onClick={discard} disabled={!isDirty || save.isPending}>
                <RotateCcw /> Discard
              </Button>
              <Button type="submit" form={FORM_ID} disabled={!isDirty || save.isPending}>
                <SaveIcon className={cn(save.isPending && "animate-spin")} /> Save profile
              </Button>
            </>
          }
        />

        {unanswered.length ? (
          <div className="flex flex-col gap-3 rounded-xl border border-warning/25 bg-warning-soft px-4 py-3 sm:flex-row sm:items-center">
            <ShieldAlert className="size-4 shrink-0 text-warning" />
            <p className="flex-1 text-xs leading-relaxed text-text-2">
              <span className="font-medium text-text-1">Not stated in your saved profile: {unanswered.join(", ")}.</span>{" "}
              Applications that ask for these wait in the Action inbox until you answer.
            </p>
            <Button type="button" size="sm" variant="outline" onClick={() => setSection("compensation")}>
              Answer them
            </Button>
          </div>
        ) : null}

        <Tabs
          value={section}
          onValueChange={(next) => setSection(next as SectionId)}
          orientation="vertical"
          className="grid gap-6 lg:grid-cols-[15rem_minmax(0,1fr)]"
        >
          <aside className="space-y-4 lg:sticky lg:top-[calc(var(--topbar-height)+1rem)] lg:self-start">
            <CompletenessCard values={values} onJump={setSection} />
            <TabsList
              aria-label="Profile sections"
              className="grid h-auto w-full grid-cols-2 gap-1 bg-transparent p-0 sm:grid-cols-3 lg:flex lg:flex-col lg:items-stretch lg:gap-0.5"
            >
              {SECTIONS.map((item) => {
                const Icon = item.icon;
                const hasError = errorSections.has(item.id);
                const complete = item.id !== "resumes" && sectionComplete(item.id);
                return (
                  <TabsTrigger
                    key={item.id}
                    value={item.id}
                    className="group/trig h-9 w-full min-w-0 justify-start gap-2.5 rounded-lg px-3 text-[13px] text-text-2 hover:bg-surface-2 hover:text-text-1 data-active:bg-surface-2 data-active:text-text-1 data-active:shadow-none lg:w-full dark:data-active:border-line dark:data-active:bg-surface-2"
                  >
                    <Icon className="size-4 text-text-3 group-data-active/trig:text-violet" />
                    <span className="min-w-0 flex-1 truncate text-left">{item.label}</span>
                    {hasError ? (
                      <span className="size-1.5 rounded-full bg-danger" aria-label="has errors" />
                    ) : complete ? (
                      <span className="size-1.5 rounded-full bg-success/70" aria-label="complete" />
                    ) : null}
                  </TabsTrigger>
                );
              })}
            </TabsList>
          </aside>

          <div className="min-w-0">
            <AnimatePresence mode="wait" initial={false}>
              <motion.div
                key={active.id}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -4 }}
                transition={{ duration: 0.18, ease: [0.22, 1, 0.36, 1] }}
                className="mb-4"
              >
                <h2 className="font-heading text-lg font-semibold tracking-tight text-text-1">{active.title}</h2>
                <p className="mt-0.5 text-sm text-text-3">{active.description}</p>
              </motion.div>
            </AnimatePresence>

            {serverError && section !== "resumes" ? (
              <div role="alert" className="mb-4 flex gap-3 rounded-xl border border-danger/25 bg-danger-soft p-4">
                <AlertTriangle className="mt-0.5 size-4 shrink-0 text-danger" />
                <div className="space-y-1 text-xs text-text-2">
                  <p className="text-sm font-medium text-text-1">The profile was not saved</p>
                  <p>{serverError.message}</p>
                  {serverError.details.length ? (
                    <ul className="list-disc pl-4">
                      {serverError.details.map((detail) => (
                        <li key={detail}>{detail}</li>
                      ))}
                    </ul>
                  ) : null}
                </div>
              </div>
            ) : null}

            <TabsContent value="resumes" className="mt-0">
              <ResumePanel onApplyProposal={applyProposal} />
            </TabsContent>

            <form id={FORM_ID} noValidate onSubmit={form.handleSubmit(onValid, onInvalid)}>
              {(Object.keys(FORM_SECTIONS) as Array<keyof typeof FORM_SECTIONS>).map((id) => {
                const Section = FORM_SECTIONS[id];
                return (
                  <TabsContent key={id} value={id} className="mt-0">
                    <div className="orbit-card p-5 sm:p-6">
                      <Section />
                    </div>
                  </TabsContent>
                );
              })}
            </form>
          </div>
        </Tabs>
      </div>

      <AnimatePresence>
        {isDirty ? (
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 16 }}
            transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
            className="pointer-events-none fixed inset-x-0 bottom-5 z-40 flex justify-center px-4"
          >
            <div
              role="status"
              className="orbit-glass pointer-events-auto flex items-center gap-3 rounded-full py-1.5 pr-1.5 pl-4 shadow-raised"
            >
              <span className="size-1.5 animate-pulse-soft rounded-full bg-violet" />
              <span className="text-xs text-text-2">Unsaved changes</span>
              <Button type="button" size="sm" variant="ghost" className="rounded-full" onClick={discard} disabled={save.isPending}>
                Discard
              </Button>
              <Button type="submit" form={FORM_ID} size="sm" className="rounded-full" disabled={save.isPending}>
                <SaveIcon className={cn(save.isPending && "animate-spin")} /> Save profile
              </Button>
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </FormProvider>
  );
}
