// Imposition en livret (piqûre à cheval), comme « Livret » dans Acrobat :
// deux pages côte à côte par face de feuille paysage, recto verso retourné sur
// le bord court ; la pile pliée au milieu donne les pages dans l'ordre.

// Faces imprimées, dans l'ordre : recto de la feuille 1, verso de la feuille 1,
// recto de la feuille 2… Chaque face porte deux index de page (0 = première),
// null pour une page blanche ajoutée afin d'atteindre un multiple de 4.
//   binding : 'left' (lecture de gauche à droite) ou 'right' (reliure à droite).
//   sides   : 'both', 'front' (rectos seuls) ou 'back' (versos seuls), pour un
//             recto verso manuel.
export function bookletSides(pageCount, { binding = 'left', sides = 'both' } = {}) {
  const total = Math.ceil(Math.max(pageCount, 1) / 4) * 4;
  const page = (index) => (index < pageCount ? index : null);
  const result = [];
  for (let sheet = 0; sheet < total / 4; sheet += 1) {
    const front = { sheet, side: 'front', left: page(total - 1 - 2 * sheet), right: page(2 * sheet) };
    const back = { sheet, side: 'back', left: page(2 * sheet + 1), right: page(total - 2 - 2 * sheet) };
    for (const face of [front, back]) {
      if (sides !== 'both' && face.side !== sides) continue;
      if (binding === 'right') [face.left, face.right] = [face.right, face.left];
      result.push(face);
    }
  }
  return result;
}

export function bookletSheetCount(pageCount) {
  return Math.ceil(Math.max(pageCount, 1) / 4);
}
