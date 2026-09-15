/**
 * Lookups keyed by something the user controls.
 *
 * `MAP[key] || fallback` reads as "the entry, or the fallback for anything
 * unknown", and that is not what it does. Every object literal inherits from
 * `Object.prototype`, so a handful of keys nobody put in the map still come
 * back truthy and skip the fallback entirely:
 *
 *   MAP["toString"]     -> a function
 *   MAP["constructor"]  -> the Object constructor
 *   MAP["__proto__"]    -> Object.prototype, truthy and not callable
 *
 * Which of those hurts depends on what the caller does next. Rendering one
 * puts "[object Object]" on the page; calling one throws `read is not a
 * function` and takes the render down with it. `/armory?sort=__proto__` did
 * exactly that, and `#__proto__` in the same page's hash made the tab an
 * object rather than a string.
 *
 * An own-property check is the whole fix. Use this anywhere the key arrives
 * from a URL, a form, or a row the user stored earlier -- and prefer
 * validating against a known set at the boundary as well, where there is one.
 */
export function fromMap(map, key, fallback) {
  return Object.hasOwn(map, key) ? map[key] : fallback;
}
