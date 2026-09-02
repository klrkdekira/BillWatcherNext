import { Link, useLocation } from "react-router";

export function NotFoundPage() {
  const location = useLocation();
  return (
    <>
      <h1 className="display">Nothing is published at that identifier</h1>
      <p className="lede">
        <code>{location.pathname}</code> names no work, expression or file in this release.
      </p>
      <div className="notice">
        <p>
          A bill can be absent for a reason rather than by accident: a reading that cannot account
          for the document it came from is rejected by the fidelity gate and is not published at
          all, in preference to publishing a reading nobody has checked.
        </p>
      </div>
      <p>
        <Link to="/">Browse the catalogue</Link>
      </p>
    </>
  );
}
