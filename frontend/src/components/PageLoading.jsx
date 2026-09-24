/**
 * What shows while a page's code is being fetched the first time it is opened.
 *
 * The same spinner the rest of the app uses while data loads, so a page that
 * is still arriving looks like a page that is still loading -- which it is.
 */
export default function PageLoading() {
  return (
    <div className="loading-row" role="status" aria-live="polite">
      <div className="spinner" />
      Loading…
    </div>
  );
}
