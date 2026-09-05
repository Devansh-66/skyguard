# Team photographs

Drop files here and the team page picks them up on the next build. Nothing to
edit in code.

Filenames must match the `id` in `web/src/routes/TeamRoute.tsx`:

    devansh.jpg   samarth.jpg   shaurya.jpg
    simran.jpg    ujjwal.jpg    sneh.jpg

Square-ish, at least 600 px on the short side, JPEG. The cards crop to 4:3 and
centre the image, so leave a little room around the face.

Any file that is missing simply renders as an initial tile marked "photo to
come" — an incomplete set is fine and looks deliberate, so add them as they
arrive rather than waiting for all six.

Social links are the same story: fill in `github` / `linkedin` on a member in
that file and the chip becomes a live link; leave it out and it stays a grey
placeholder rather than a link to nowhere.
