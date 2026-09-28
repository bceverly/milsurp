/**
 * Orders for the names this application lists: shared by the Armory and the
 * Market pages, which both sort calibers and want them in bore order.
 */

//: Names here are mostly numbers, and a plain string sort reads them wrong:
//: ".30-06" lands after ".303", "M1903" after "M191", and "Model 9" after
//: "Model 1873". Numeric collation compares each run of digits as a number,
//: which is the order somebody looking for a cartridge expects. Base
//: sensitivity so case and accents do not split "Schmidt-Rubin" from
//: "Schmidt–Rubin".
export const COLLATOR = new Intl.Collator(undefined, {
  numeric: true,
  sensitivity: "base",
});

//: A caliber's leading number is not one kind of measurement, which is why
//: the general collator gets this list wrong. It reads the digits as ordinals,
//: so ".303 British" lands after ".45 ACP" -- 303 against 45 -- when as bore
//: diameters they are 0.303" and 0.45" and the .303 belongs between .30-06 and
//: .308. Three shapes, and the catalog holds nothing else:
//:
//:   .303 British        a fraction of an inch -- 0.303
//:   7.62x54R            millimetres -- 7.62
//:   12 gauge            a bore gauge, where a bigger number is a smaller bore
//:
//: Grouped by shape and then numeric within the group, rather than converted
//: to a common unit. Both are defensible; this one is legible. Interleaving
//: ".30-06 Springfield" with "7.62x54R" because they are the same bore is
//: true, and nobody scanning for a cartridge reads a list that way.
const INCH_BORE = /^\.(\d+)/;
const GAUGE = /^(\d+)\s*(?:gauge|ga\b)/i;
const MILLIMETRES = /^(\d+(?:\.\d+)?)/;

/** Which block a caliber belongs in, and where in it. */
function caliberRank(name) {
  const text = (name || "").trim();
  const gauge = GAUGE.exec(text);
  // Before the millimetre rule, which would otherwise read "12 gauge" as 12mm.
  if (gauge) return [2, Number(gauge[1])];
  const inch = INCH_BORE.exec(text);
  // The digits after the dot are the fraction, so ".45-70" is 0.45 and the 70
  // is grains of powder -- not part of the bore at all.
  if (inch) return [0, Number(`0.${inch[1]}`)];
  const millimetres = MILLIMETRES.exec(text);
  if (millimetres) return [1, Number(millimetres[1])];
  return [3, 0];
}

export function compareCalibers(left, right) {
  const [leftGroup, leftBore] = caliberRank(left);
  const [rightGroup, rightBore] = caliberRank(right);
  // Same bore is the common case -- .38 Special, .38 Super and .380 ACP are
  // all 0.38 -- so the name settles it.
  return leftGroup - rightGroup || leftBore - rightBore || COLLATOR.compare(left, right);
}
