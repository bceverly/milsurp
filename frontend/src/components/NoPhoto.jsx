/**
 * What a listing shows when it has no photograph: a vendor that publishes none
 * (Nickerson Military's list is text, Joe Salter's robots.txt keeps us out of
 * its images), or one not downloaded yet.
 *
 * The mark faded into a pale square, so an empty frame reads as "nothing to
 * show" rather than as a broken image. Drawn by scripts/brand.py from the same
 * geometry as the favicon, which also writes the copy the emails attach.
 *
 * Sized by the caller's class, exactly like the photograph it stands in for.
 */
const SRC = `${import.meta.env.BASE_URL}no-photo.svg`;

export default function NoPhoto({ className, caption = "No photo available" }) {
  return (
    <img
      className={["no-photo", className].filter(Boolean).join(" ")}
      src={SRC}
      alt=""
      title={caption}
    />
  );
}
