# Task 04: ARC Puzzles Notes

- **01**: Downward gravity — non-zero cells fall to the bottom of their respective columns preserving vertical order.
- **02**: Recolor 4-connected `5`-components: smallest component becomes `2`, largest becomes `1`, others remain `5`.
- **03**: Each non-zero color `c` adjacent (4-way) to a `5` shoots a ray of `c` away from `5` to the grid boundary.
- **04**: Split across the vertical `5`-divider: output cell is `3` iff exactly one of the corresponding left/right cells is non-zero (XOR), else `0`.
- **05**: Crop the bounding box of the unique-shape 4-connected object (up to rotation and reflection).
- **06**: Complete the 2D periodic pattern by filling `0` holes using the smallest consistent `(row_period, col_period)`.
- **07**: Fill completely enclosed `0` interiors (unreachable from the grid border) with `4`.
- **08**: Above the `5`-bar, columns define a color mapping `row0 -> row1`; below the `5`-bar, recolor cells using the mapping and erase unmapped colors to `0`.
- **09**: Slide all non-`8` 4-connected objects as rigid bodies toward the `8`-wall until blocked by the `8`-wall or previously settled objects.
- **10**: Recolor each 4-connected `5`-component to the count of enclosed `0`-holes inside it (components with 0 holes become `0`).
