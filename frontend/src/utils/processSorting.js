const SORT_KEYS = new Set(['pid', 'name', 'cpu_percent', 'memory_percent'])
const NAME_COLLATOR = new Intl.Collator(undefined, { sensitivity: 'base' })

export function sortProcessRows(rows, sort = {}) {
  const prop = SORT_KEYS.has(sort.prop) ? sort.prop : 'pid'
  const direction = sort.order === 'descending' ? -1 : 1
  return [...rows].sort((left, right) => {
    if (prop === 'name') {
      const comparison = NAME_COLLATOR.compare(String(left.name || ''), String(right.name || ''))
      return comparison * direction || (Number(left.pid) - Number(right.pid))
    }
    const a = left[prop] === null || left[prop] === undefined ? NaN : Number(left[prop])
    const b = right[prop] === null || right[prop] === undefined ? NaN : Number(right[prop])
    if (!Number.isFinite(a)) return Number.isFinite(b) ? 1 : 0
    if (!Number.isFinite(b)) return -1
    return (a - b) * direction || (Number(left.pid) - Number(right.pid))
  })
}
