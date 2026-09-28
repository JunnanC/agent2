export type PortalEvent = {
  id: string
  type: string
  data: Record<string, unknown>
}

export type EventConnectionState = 'connecting' | 'live' | 'backoff' | 'polling' | 'closed'

export type PortalEventClientOptions = {
  url?: string
  onEvent?: (event: PortalEvent) => void
  onError?: (error: unknown) => void
  onStateChange?: (state: EventConnectionState) => void
  poll?: () => Promise<PortalEvent[]>
  maxBackoffMs?: number
}

type Listener = (event: PortalEvent) => void

/** One resumable SSE connection per portal. Tokens are deliberately not accepted here. */
export class PortalEventClient {
  private readonly url: string
  private readonly poll?: () => Promise<PortalEvent[]>
  private readonly maxBackoffMs: number
  private readonly listeners = new Set<Listener>()
  private readonly seen = new Set<string>()
  private controller: AbortController | undefined
  private running = false
  private retry = 0
  private state: EventConnectionState = 'closed'
  private cursor = ''

  constructor(options: PortalEventClientOptions = {}) {
    this.url = options.url ?? '/api/v2/events/stream'
    this.poll = options.poll
    this.maxBackoffMs = options.maxBackoffMs ?? 30_000
    if (options.onEvent) this.listeners.add(options.onEvent)
    this.onError = options.onError
    this.onStateChange = options.onStateChange
  }

  private readonly onError?: (error: unknown) => void
  private readonly onStateChange?: (state: EventConnectionState) => void

  get connectionState(): EventConnectionState { return this.state }
  get lastEventId(): string { return this.cursor }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  start(): void {
    if (this.running) return
    this.running = true
    void this.connect()
  }

  stop(): void {
    this.running = false
    this.controller?.abort()
    this.controller = undefined
    this.setState('closed')
  }

  private setState(state: EventConnectionState): void {
    if (this.state === state) return
    this.state = state
    this.onStateChange?.(state)
  }

  private emit(event: PortalEvent): void {
    if (event.id && this.seen.has(event.id)) return
    if (event.id) {
      this.seen.add(event.id)
      if (this.seen.size > 512) this.seen.delete(this.seen.values().next().value ?? '')
      this.cursor = event.id
    }
    for (const listener of this.listeners) listener(event)
  }

  private async connect(): Promise<void> {
    while (this.running) {
      this.setState(this.retry ? 'backoff' : 'connecting')
      this.controller = new AbortController()
      try {
        const headers = new Headers({ Accept: 'text/event-stream' })
        if (this.cursor) headers.set('Last-Event-ID', this.cursor)
        const response = await fetch(this.url, { credentials: 'include', headers, signal: this.controller.signal })
        if (!response.ok || !response.body) throw new Error(`SSE_${response.status}`)
        this.retry = 0
        this.setState('live')
        await this.consume(response.body)
        if (this.running && this.poll) throw new Error('SSE_CLOSED')
      } catch (error) {
        if (!this.running) break
        this.onError?.(error)
        this.retry += 1
        if (this.poll) {
          this.setState('polling')
          try {
            for (const event of await this.poll()) this.emit(event)
          } catch (pollError) {
            this.onError?.(pollError)
          }
        }
        const delay = Math.min(this.maxBackoffMs, 500 * 2 ** Math.min(this.retry, 6))
        await new Promise((resolve) => window.setTimeout(resolve, delay))
      } finally {
        this.controller = undefined
      }
    }
  }

  private async consume(body: ReadableStream<Uint8Array>): Promise<void> {
    const reader = body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let id = ''
    let type = 'message'
    let data: string[] = []
    const flush = () => {
      if (!data.length) return
      let payload: Record<string, unknown> = {}
      try { payload = JSON.parse(data.join('\n')) as Record<string, unknown> } catch { payload = { raw: data.join('\n') } }
      this.emit({ id, type, data: payload })
      id = ''; type = 'message'; data = []
    }
    while (this.running) {
      const result = await reader.read()
      if (result.done) { flush(); break }
      buffer += decoder.decode(result.value, { stream: true })
      const lines = buffer.split(/\r?\n/)
      buffer = lines.pop() ?? ''
      for (const line of lines) {
        if (!line) { flush(); continue }
        if (line.startsWith(':')) continue
        const separator = line.indexOf(':')
        const field = separator < 0 ? line : line.slice(0, separator)
        const value = separator < 0 ? '' : line.slice(separator + 1).replace(/^ /, '')
        if (field === 'id') id = value
        else if (field === 'event') type = value || 'message'
        else if (field === 'data') data.push(value)
      }
    }
    reader.releaseLock()
  }
}

export function openPortalEventStream(
  onEvent?: (event: PortalEvent) => void,
  onError?: (error: unknown) => void,
): PortalEventClient {
  const client = new PortalEventClient({ onEvent, onError })
  client.start()
  return client
}
