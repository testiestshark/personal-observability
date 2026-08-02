import { createStart, createCsrfMiddleware, createMiddleware } from "@tanstack/react-start";

import { renderErrorPage } from "./lib/error-page";
import { attachSupabaseAuth } from "@/integrations/supabase/auth-attacher";

const errorMiddleware = createMiddleware().server(async ({ next }) => {
  try {
    return await next();
  } catch (error) {
    if (error != null && typeof error === "object" && "statusCode" in error) {
      throw error;
    }
    console.error(error);
    return new Response(renderErrorPage(), {
      status: 500,
      headers: { "content-type": "text/html; charset=utf-8" },
    });
  }
});

// Start installs this automatically when src/start.ts is absent; defining the
// file opts out, so re-add it explicitly to keep server functions protected
// from cross-site requests.
const csrfMiddleware = createCsrfMiddleware({
  filter: (ctx) => ctx.handlerType === "serverFn",
});

// DO NOT re-add `attachSupabaseAuth` here. It is a `.client()` middleware, so it
// runs in the browser on every server-function call and eagerly constructs the
// generated Supabase client from `@/integrations/supabase/client`, which throws
// when VITE_SUPABASE_* are absent from the client bundle — as they are on the
// hosted build. That broke sign-in in production while passing locally, because
// .env.local happens to define those variables.
//
// Auth is cookie-based (see src/lib/auth/), so no bearer token needs attaching:
// same-origin cookies are sent with serverFn requests automatically.
export const startInstance = createStart(() => ({
  functionMiddleware: [attachSupabaseAuth],
  requestMiddleware: [errorMiddleware, csrfMiddleware],
}));
