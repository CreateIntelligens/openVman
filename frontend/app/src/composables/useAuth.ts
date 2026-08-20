import { readonly, ref } from "vue"

import {
  getCurrentAccount,
  login as loginRequest,
  logout as logoutRequest,
  temporaryLogin as temporaryLoginRequest,
  type AccountProfile,
} from "../api/auth"
import {
  setForbiddenHandler,
  setUnauthorizedHandler,
} from "../api/http"

const account = ref<AccountProfile | null>(null)
const loading = ref(true)
const forbidden = ref(false)
let handlersInstalled = false

const PUBLIC_OPENVMAN_PREFIX = "/openvman"

function publicAppPath(path: string): string {
  const pathname = window.location.pathname
  const prefix = pathname === PUBLIC_OPENVMAN_PREFIX || pathname.startsWith(`${PUBLIC_OPENVMAN_PREFIX}/`)
    ? PUBLIC_OPENVMAN_PREFIX
    : ""
  return `${prefix}${path}`
}

function replacePath(path: string): void {
  window.history.replaceState(null, "", path)
}

function expireSession(): void {
  account.value = null
  forbidden.value = false
  loading.value = false
  if (window.location.pathname !== publicAppPath("/login")) replacePath(publicAppPath("/login"))
}

function installHandlers(): void {
  if (handlersInstalled) return
  handlersInstalled = true
  setUnauthorizedHandler(expireSession)
  setForbiddenHandler(() => {
    forbidden.value = true
  })
}

async function bootstrap(): Promise<void> {
  installHandlers()
  loading.value = true
  try {
    account.value = await getCurrentAccount()
    forbidden.value = false
    if (window.location.pathname === publicAppPath("/login")) replacePath(publicAppPath("/"))
  } catch {
    expireSession()
  } finally {
    loading.value = false
  }
}

function completeLogin(profile: AccountProfile): void {
  account.value = profile
  forbidden.value = false
  replacePath(publicAppPath("/"))
}

async function login(username: string, password: string): Promise<void> {
  completeLogin(await loginRequest(username, password))
}

async function loginTemporary(password: string): Promise<void> {
  completeLogin(await temporaryLoginRequest(password))
}

async function logout(): Promise<void> {
  try {
    await logoutRequest()
  } finally {
    expireSession()
  }
}

function clearForbidden(): void {
  forbidden.value = false
}

export function useAuth() {
  return {
    account: readonly(account),
    loading: readonly(loading),
    forbidden: readonly(forbidden),
    bootstrap,
    login,
    loginTemporary,
    logout,
    clearForbidden,
  }
}
