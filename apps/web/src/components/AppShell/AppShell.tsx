import { Link, Outlet } from 'react-router-dom'
import styles from './AppShell.module.css'

/**
 * Minimal site chrome shared across every route -- a topbar with the site
 * name and primary nav, plus a footer, both linking to `/about`. This is the
 * `.topbar`/`.foot` pattern speccd in docs/design-system.html (lines
 * ~383-393, ~724-725) but never actually built until now. Pages render
 * inside via `<Outlet />`; this component stays route-agnostic (it doesn't
 * import any page) so it can live under `components/` without violating the
 * components-must-not-import-pages rule in `.dependency-cruiser.cjs`.
 */
export function AppShell() {
  return (
    <>
      <header className={styles.topbar}>
        <Link to="/" className={styles.name}>
          My Team Is Better
        </Link>
        <nav className={styles.nav} aria-label="Primary">
          <Link to="/about" className={styles.navLink}>
            How This Works
          </Link>
        </nav>
      </header>
      <Outlet />
      <footer className={styles.foot}>
        <span>
          Palette pulls from the program-cover / leather / chalkboard era of the
          sport, not any one school&rsquo;s actual branding.
        </span>
        <Link to="/about" className={styles.footLink}>
          Credits &amp; methodology
        </Link>
      </footer>
    </>
  )
}
