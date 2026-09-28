/**
 * A table column header that sorts, shared by the pages that have them.
 *
 * `sort` is `{ key, direction }`, and `onSort(key)` is called with this
 * column's key; the page decides what a click does to the direction.
 */
export default function SortHeader({ label, sortKey, sort, onSort, className }) {
  const active = sort.key === sortKey;
  return (
    <th
      className={className}
      aria-sort={
        active ? (sort.direction === "asc" ? "ascending" : "descending") : "none"
      }
    >
      <button
        type="button"
        className={`table__sort${active ? " table__sort--active" : ""}`}
        // A title rather than an aria-label. The visible text is already the
        // accessible name (the arrow beside it is aria-hidden), and aria-sort
        // on the cell carries the state -- so a label here would only restate
        // them. It would also collide: an aria-label of "Sort by Name" makes
        // this button answer to getByLabel("Name"), which is how the form
        // fields are addressed, and every "Name"/"Kind"/"Models" lookup in the
        // suite started matching two elements.
        title={`Sort by ${label}`}
        onClick={() => onSort(sortKey)}
      >
        {label}
        <span className="table__sort-mark" aria-hidden="true">
          {active ? (sort.direction === "asc" ? "▲" : "▼") : "▾"}
        </span>
      </button>
    </th>
  );
}
