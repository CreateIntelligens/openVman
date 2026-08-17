import { useState, type FormEvent } from "react";

import { useAuth } from "../../context/AuthContext";

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

export function AuthLoadingState() {
  return (
    <div className="flex h-dvh items-center justify-center bg-surface text-content">
      <div className="flex items-center gap-3 text-sm text-content-muted" role="status">
        <span className="h-5 w-5 animate-spin rounded-full border-2 border-border border-t-primary" />
        正在確認登入狀態…
      </div>
    </div>
  );
}

export function LoginScreen() {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!username.trim() || !password) {
      setError("請輸入帳號與密碼");
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      await login(username.trim(), password);
    } catch (nextError) {
      setError(errorMessage(nextError, "登入失敗，請稍後再試"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="flex min-h-dvh items-center justify-center bg-surface-sunken p-6 text-content">
      <section className="w-full max-w-md rounded-xl border border-border bg-surface-raised p-8 shadow-xl">
        <div className="mb-8 flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-lg bg-primary/15 text-primary">
            <span className="material-symbols-outlined text-[1.5rem]">neurology</span>
          </div>
          <div>
            <h1 className="text-xl font-semibold">登入 openVman</h1>
            <p className="mt-1 text-sm text-content-muted">管理知識庫、人物與聲音資源</p>
          </div>
        </div>

        <form className="space-y-5" onSubmit={handleSubmit}>
          {error && (
            <div className="rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger" role="alert">
              {error}
            </div>
          )}
          <label className="block text-sm font-medium">
            帳號
            <input
              className="input mt-2"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              autoComplete="username"
              disabled={submitting}
              autoFocus
            />
          </label>
          <label className="block text-sm font-medium">
            密碼
            <input
              className="input mt-2"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
              disabled={submitting}
            />
          </label>
          <button className="btn btn-primary w-full" disabled={submitting} type="submit">
            {submitting ? "登入中…" : "登入"}
          </button>
        </form>
      </section>
    </main>
  );
}

export function ForbiddenState() {
  const { account, clearForbidden, logout } = useAuth();

  return (
    <main className="flex h-full items-center justify-center bg-surface p-6 text-content">
      <section className="max-w-lg rounded-xl border border-border bg-surface-raised p-8 text-center shadow-lg">
        <span className="material-symbols-outlined text-[2.5rem] text-warn">lock</span>
        <h1 className="mt-4 text-xl font-semibold">權限不足</h1>
        <p className="mt-2 text-sm text-content-muted">
          帳號「{account?.username}」沒有存取這個功能的權限。
        </p>
        <div className="mt-6 flex justify-center gap-3">
          <button className="btn btn-ghost" type="button" onClick={clearForbidden}>
            返回
          </button>
          <button className="btn btn-primary" type="button" onClick={() => void logout()}>
            登出
          </button>
        </div>
      </section>
    </main>
  );
}
