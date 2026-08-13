let cachedManual = null

async function fetchProductManual(productId) {
  if (cachedManual) return cachedManual
  try {
    const intelUrl = process.env.INTEL_SUPABASE_URL
    const intelKey = process.env.INTEL_SUPABASE_KEY
    if (!intelUrl || !intelKey) return null
    const r = await fetch(
      `${intelUrl}/rest/v1/product_manuals?product_id=eq.${productId}&select=manual&limit=1`,
      { headers: { apikey: intelKey, Authorization: `Bearer ${intelKey}` } }
    )
    const data = await r.json()
    cachedManual = data?.[0]?.manual || null
  } catch {}
  return cachedManual
}

export default async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).end()
  const { messages, system } = req.body
  const productId = process.env.VITE_PRODUCT_ID
  const manual = await fetchProductManual(productId)
  const systemPrompt = manual ? `${system}\n\nPRODUCT MANUAL:\n${manual}` : system

  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 25000)
  try {
    const r = await fetch('https://api.deepseek.com/v1/chat/completions', {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${process.env.DEEPSEEK_API_KEY}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: 'deepseek-v4-flash', max_tokens: 2048, messages: [{ role: 'system', content: systemPrompt }, ...messages] }),
      signal: controller.signal,
    })
    const data = await r.json()
    if (data.choices?.[0]?.message && !data.choices[0].message.content) {
      data.choices[0].message.content = data.choices[0].message.reasoning_content || 'Something went wrong. Please try again.'
    }
    if (!data.choices?.[0]?.message?.content && r.status !== 200) {
      return res.status(r.status).json({ error: data?.error?.message || 'Upstream request failed' })
    }
    res.status(r.status).json(data)
  } catch (err) {
    const aborted = err && err.name === 'AbortError'
    return res.status(504).json({ error: aborted ? 'Assistant request timed out. Please try again.' : 'Could not reach the assistant service.' })
  } finally {
    clearTimeout(timeout)
  }
}
