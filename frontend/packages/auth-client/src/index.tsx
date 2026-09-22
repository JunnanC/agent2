/* eslint-disable react-refresh/only-export-components */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import {
  ApiError,
  apiRequest,
  apiRequestWithMetadata,
  type ApiResult,
  type MeData,
  type MeResponse,
} from '@edu/api-client'
import { useQueryClient } from '@tanstack/react-query'

export type Portal = 'USER' | 'TEACHING' | 'PLATFORM'

export interface LoginInput {
  identifier: string
  password: string
}

export interface SessionState {
  status: 'loading' | 'anonymous' | 'authenticated' | 'denied' | 'error'
  me: MeData | null
  etag: string | null
  error: ApiError | null
}

interface SessionContextValue extends SessionState {
  refresh: () => Promise<void>
  signIn: (input: LoginInput) => Promise<void>
  signOut: () => Promise<void>
  signOutAll: () => Promise<void>
  updateMe: (me: MeData, etag: string | null) => void
}

const SessionContext = createContext<SessionContextValue | null>(null)

export function initializeCsrf(): Promise<unknown> {
  return apiRequest('/api/v2/auth/csrf')
}

export function getMe(signal?: AbortSignal): Promise<ApiResult<MeResponse>> {
  return apiRequestWithMetadata('/api/v2/me', { signal })
}

export function login(input: LoginInput): Promise<ApiResult<MeResponse>> {
  return apiRequestWithMetadata('/api/v2/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
}

export async function logout(): Promise<void> {
  await apiRequest('/api/v2/auth/logout', { method: 'POST' })
}

export async function logoutAll(): Promise<void> {
  await apiRequest('/api/v2/auth/logout-all', { method: 'POST' })
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [state, setState] = useState<SessionState>({
    status: 'loading',
    me: null,
    etag: null,
    error: null,
  })

  const refresh = useCallback(async () => {
    setState((current) => ({ ...current, status: 'loading', error: null }))
    try {
      await initializeCsrf()
      const result = await getMe()
      setState({ status: 'authenticated', me: result.payload.data, etag: result.etag, error: null })
    } catch (error) {
      const apiError = error instanceof ApiError ? error : null
      if (apiError?.status === 401) {
        queryClient.clear()
        setState({ status: 'anonymous', me: null, etag: null, error: apiError })
      } else if (apiError?.status === 403) {
        queryClient.clear()
        setState({ status: 'denied', me: null, etag: null, error: apiError })
      } else {
        setState({ status: 'error', me: null, etag: null, error: apiError })
      }
    }
  }, [queryClient])

  useEffect(() => { void refresh() }, [refresh])

  const signIn = useCallback(async (input: LoginInput) => {
    await initializeCsrf()
    const result = await login(input)
    queryClient.clear()
    setState({ status: 'authenticated', me: result.payload.data, etag: result.etag, error: null })
  }, [queryClient])

  const clear = useCallback(() => {
    queryClient.clear()
    setState({ status: 'anonymous', me: null, etag: null, error: null })
  }, [queryClient])
  const signOut = useCallback(async () => { try { await logout() } finally { clear() } }, [clear])
  const signOutAll = useCallback(async () => { try { await logoutAll() } finally { clear() } }, [clear])
  const updateMe = useCallback((me: MeData, etag: string | null) => {
    setState({ status: 'authenticated', me, etag, error: null })
  }, [])
  const value = useMemo(
    () => ({ ...state, refresh, signIn, signOut, signOutAll, updateMe }),
    [state, refresh, signIn, signOut, signOutAll, updateMe],
  )
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}

export function useSession(): SessionContextValue {
  const value = useContext(SessionContext)
  if (!value) throw new Error('useSession must be used inside SessionProvider')
  return value
}
