import { zodResolver } from "@hookform/resolvers/zod";
import { Sparkles } from "lucide-react";
import { useForm } from "react-hook-form";
import { Navigate, useLocation } from "react-router-dom";
import { z } from "zod";
import { errorMessage } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Card, Field, Input } from "@/components/ui/primitives";
import { useAuth } from "@/lib/auth";
import { useState } from "react";

const schema = z.object({
  email: z.string().min(1, "Email is required").email("Enter a valid email"),
  password: z.string().min(1, "Password is required"),
});
type Values = z.infer<typeof schema>;

export default function LoginPage() {
  const { user, login } = useAuth();
  const location = useLocation();
  const [error, setError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<Values>({ resolver: zodResolver(schema) });

  if (user) return <Navigate to={(location.state as { from?: string } | null)?.from ?? "/"} replace />;

  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <div className="relative hidden flex-col justify-between overflow-hidden bg-gradient-to-br from-[#0b2a6f] via-[#1d5fd8] to-[#7cc4fb] p-12 text-white lg:flex">
        <div aria-hidden className="absolute -right-24 -top-24 h-96 w-96 rounded-full bg-white/10 blur-3xl" />
        <div aria-hidden className="absolute -bottom-32 -left-16 h-96 w-96 rounded-full bg-sky-200/20 blur-3xl" />
        <div className="relative flex items-center gap-2 text-lg font-semibold">
          <span className="grid h-10 w-10 place-items-center rounded-xl bg-white/20 ring-1 ring-white/30">
            <Sparkles className="h-5 w-5" aria-hidden />
          </span>
          IncidentIQ
        </div>
        <div className="relative space-y-4">
          <h2 className="text-4xl font-semibold leading-tight">Explainable triage for IT incidents.</h2>
          <p className="max-w-md text-blue-100">
            Classify, prioritise and route with transparent models, calibrated confidence and a human-approved audit trail.
          </p>
        </div>
        <p className="relative text-xs text-blue-100">IIT Guwahati · DA377 · academic demonstration</p>
      </div>
      <div className="grid place-items-center bg-gradient-to-br from-blue-50 via-white to-sky-50 p-4">
      <Card className="w-full max-w-sm p-6">
        <div className="mb-5 flex items-center gap-2">
          <span className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-[#123a99] to-[#38a8f5] text-white">
            <Sparkles className="h-4 w-4" aria-hidden />
          </span>
          <div>
            <h1 className="text-lg font-semibold">IncidentIQ-Triage</h1>
            <p className="text-xs text-slate-500">Explainable ML incident triage · academic demo</p>
          </div>
        </div>
        <form
          className="space-y-4"
          noValidate
          onSubmit={handleSubmit(async (v) => {
            setError(null);
            try {
              await login(v.email, v.password);
            } catch (e) {
              setError(errorMessage(e));
            }
          })}
        >
          <Field label="Email" htmlFor="email" error={errors.email?.message}>
            <Input id="email" type="email" autoComplete="username" {...register("email")} />
          </Field>
          <Field label="Password" htmlFor="password" error={errors.password?.message}>
            <Input id="password" type="password" autoComplete="current-password" {...register("password")} />
          </Field>
          {error && (
            <p role="alert" className="rounded-xl bg-rose-50 px-3 py-2 text-sm text-rose-700">
              {error}
            </p>
          )}
          <Button type="submit" className="w-full" disabled={isSubmitting}>
            {isSubmitting ? "Signing in…" : "Sign in"}
          </Button>
        </form>
        <p className="mt-4 text-xs text-slate-500">
          Demo accounts are synthetic (<code>*@synthetic.example</code>); the password is whatever{" "}
          <code>DEMO_PASSWORD</code> you set when seeding the backend.
        </p>
      </Card>
      </div>
    </div>
  );
}
