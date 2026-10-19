# The two fan videos

The fair has two hologram fans, each playing its own looping video. Together they cover
Mexico's culture in two themes. Each piece shows its **name and place** as a title,
added at assembly time in one shared design (see "Names" below).

Pieces live in two toolkit folders. `show/` holds the first 15 pieces (fixed 1080 px
engine). `show2/` holds the newer pieces (resolution-independent engine, renders at any
size with `?size=N`). Each video is a playlist in `shows/` that mixes pieces from both
folders.

## Gente y Lugares (People & Places): the LARGE fan

A journey across Mexico. It begins with the map drawing itself, travels through its
places and the people who keep its traditions alive, and ends with a fiesta of
fireworks that leads back to the map. Transition: the "horizonte"
(`show2/transitions/horizonte.html`), a rising horizon of light with the sun on it. As
the journey goes on, the sun moves across the sky and the moon takes over for the
night pieces.

| # | Piece | Name / place |
|---|---|---|
| 1 | show/02-mapa | MÉXICO |
| 2 | show2/01-amanecer-teotihuacan | TEOTIHUACAN / Estado de México |
| 3 | show/13-aguila-nopal | TENOCHTITLAN / Ciudad de México |
| 4 | show2/13-cdmx-noche | CIUDAD DE MÉXICO / Ángel de la Independencia · Bellas Artes |
| 5 | show/06-ajolote | AJOLOTE / Xochimilco, Ciudad de México |
| 6 | show/05-mariposas | MARIPOSA MONARCA / Michoacán |
| 7 | show2/10-mariachi | MARIACHI / Jalisco |
| 8 | show2/11-jarabe-tapatio | JARABE TAPATÍO / Jalisco |
| 9 | show2/12-danza-de-la-pluma | DANZA DE LA PLUMA / Guelaguetza, Oaxaca |
| 10 | show2/09-voladores | VOLADORES DE PAPANTLA / Veracruz |
| 11 | show/04-chichen-itza | CHICHÉN ITZÁ / Yucatán |
| 12 | show2/03-cenote | CENOTE / Yucatán |
| 13 | show2/04-jaguar | JAGUAR / Selva Lacandona, Chiapas |
| 14 | show2/08-taqueria | TACOS AL PASTOR / Ciudad de México |
| 15 | show2/14-posadas | LAS POSADAS / Navidad mexicana |
| 16 | show/12-finale | ¡VIVA MÉXICO! |

## Artesanías y Tesoros (Crafts & Artifacts): the other fan

From ancient treasures to living crafts. It opens with papel picado. Next come the
great artifacts of the ancient civilisations (Olmec, Teotihuacan, Mexica), then the
crafts made today across the country. It ends with the castillo fireworks tower of
Tultepec, itself a craft, which leads back to the papel picado. Transition: the gold
"portal de luz" (`show/transitions/portal.html`).

| # | Piece | Name / place |
|---|---|---|
| 1 | show/01-intro | PAPEL PICADO / San Salvador Huixcolotla, Puebla |
| 2 | show/15-cabeza-olmeca | CABEZA OLMECA / La Venta, Tabasco |
| 3 | show2/02-quetzalcoatl | SERPIENTE EMPLUMADA / Teotihuacan |
| 4 | show/03-piedra-del-sol | PIEDRA DEL SOL / Museo Nacional de Antropología |
| 5 | show/14-talavera | TALAVERA / Puebla |
| 6 | show2/06-sarape | SARAPE DE SALTILLO / Coahuila |
| 7 | show2/05-huichol | ARTE HUICHOL / Wixárika · Jalisco y Nayarit |
| 8 | show/07-alebrije | ALEBRIJES / Oaxaca |
| 9 | show2/07-arbol-de-la-vida | ÁRBOL DE LA VIDA / Metepec, Estado de México |
| 10 | show/08-lucha | MÁSCARA DE LUCHA LIBRE / Ciudad de México |
| 11 | show/10-pinata | PIÑATA / Acolman, Estado de México |
| 12 | show/11-dia-de-muertos | LA CATRINA / Día de Muertos |
| 13 | show2/15-castillo | CASTILLO DE PIROTECNIA / Tultepec, Estado de México |

## Names

The title is drawn by a shared overlay at assembly, not by the pieces. It sits in the
**lower part of the circle (below y ≈ 780 in the 1080 frame)** from about 2.2 s after a
piece starts until about 2.2 s before it ends. Pieces should keep that lower band
calm: no key subject detail, no bright busy effects there in the middle of the piece.

## Rules for every piece

- Glowing on pure black, which is transparent on the fan. Only the inscribed circle
  is visible.
- No text inside the pieces themselves; the titles come from the overlay.
- `render(t)` is a pure function of time.
- Start from black and end dissolved to black. The first and last 1.8 s play inside
  the transition.
