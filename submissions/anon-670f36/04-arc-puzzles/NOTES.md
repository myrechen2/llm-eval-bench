# Task 04 — ARC Puzzles Notes

- **01:** All non-zero pixels fall straight downward within each column to the bottom, preserving vertical order.
- **02:** For 4-connected components of `5`s, recolor the smallest component to `2`, the largest component to `1`, and keep the rest as `5`.
- **03:** Every non-zero neighbor (4-adjacent) of a `5` extends a ray of its color away from the `5` to the grid boundary.
- **04:** Split the grid along the vertical `5`-divider into left and right `5x5` halves and output their bitwise XOR colored `3`.
- **05:** Find the single 4-connected component whose shape (under dihedral symmetry $D_4$) appears only once, and output its cropped bounding box.
- **06:** Infer the minimal 2D periodic tile $(p_r, p_c)$ from non-zero cells and fill all `0` holes accordingly.
- **07:** Fill every enclosed `0`-region (not 4-connected to the grid boundary) with color `4`.
- **08:** Rows 0–1 above the horizontal `5`-divider define a color mapping `(row0[c] -> row1[c])`; recolor components below simultaneously (erasing unmapped colors to `0`).
- **09:** Rigid 4-connected non-`8` objects slide orthogonally toward the full-line `8`-wall until blocked by the wall or other settled objects.
- **10:** Recolor each 4-connected `5`-component by the number of enclosed `0`-holes inside it (`0` holes are erased to `0`).
