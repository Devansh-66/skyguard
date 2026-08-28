/* A label/value pair in the belief tables. Values are tabular by default
 * because every one of them is a number an operator compares down a column. */
export function Field({ label, value, hint }:
  { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="field" title={hint}>
      <span className="field-label">{label}</span>
      <span className="field-value num">{value}</span>
    </div>
  )
}
