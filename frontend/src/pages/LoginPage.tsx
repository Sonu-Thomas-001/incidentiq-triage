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
    <div className="grid min-h-screen place-items-center bg-gradient-to-br from-sky-50 via-white to-violet-50 p-4">
      <Card className="w-full max-w-sm p-6">
        <div className="mb-5 flex items-center gap-2">
          <span className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-sky-400 to-violet-400 text-white">
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
  );
}
