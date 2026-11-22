import { apiData, jsonRequestOptions } from './http.js'

/** One browser-side owner for a persisted preference's latest state. */
export function createPreferenceState(url, fallback) {
  let current = null
  let revision = 0
  let writes = Promise.resolve()
  const subscribers = new Set()

  function publish(value) {
    current = value
    revision += 1
    for (const subscriber of subscribers) subscriber(value)
    return value
  }

  return {
    subscribe(subscriber) {
      subscribers.add(subscriber)
      if (current !== null) subscriber(current)
      return () => subscribers.delete(subscriber)
    },
    async load() {
      // An older GET must never replace a newer saved value.
      await writes
      const startingRevision = revision
      try {
        const response = await apiData(url, {}, fallback)
        if (startingRevision === revision) publish(response)
        return current
      } catch (error) {
        if (current !== null) return current
        throw error
      }
    },
    save(payload) {
      const operation = writes.then(async () => {
        const saved = await apiData(url, jsonRequestOptions('PUT', payload), fallback)
        return publish(saved)
      })
      writes = operation.catch(() => {})
      return operation
    },
  }
}
