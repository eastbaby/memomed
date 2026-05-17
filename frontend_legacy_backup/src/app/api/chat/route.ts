export async function POST(req: Request) {
  const { messages } = await req.json()

  // Convert UI messages to backend format
  const history = messages.map((msg: { role: string; parts: Array<{ text?: string }> }) => ({
    role: msg.role,
    content: msg.parts?.map((part) => {
      if (typeof part === 'string') return part;
      if ('text' in part) return part.text;
      return '';
    }).join('') || ''
  }))

  const lastMessage = history[history.length - 1]
  const message = lastMessage?.content || ''

  // Call the backend streaming API
  const response = await fetch('http://localhost:8010/chat/stream', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ message, history: history.slice(0, -1) }),
  })

  if (!response.ok) {
    throw new Error('Failed to fetch streaming response')
  }

  // Return the streaming response directly
  return new Response(response.body, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      'Connection': 'keep-alive',
    },
  })
}
