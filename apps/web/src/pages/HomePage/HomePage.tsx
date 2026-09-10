import { Greeting } from '../../components/Greeting/Greeting'

/**
 * Pages own composition/data-fetching; components do not import from pages
 * (enforced by dependency-cruiser -- see .dependency-cruiser.cjs).
 */
export function HomePage() {
  return <Greeting name="My Team Is Better" />
}
