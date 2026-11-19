import unittest

from cellcalc import ErrorValue, FormulaSyntaxError, Sheet
from cellcalc.refs import CellRef, addr_to_key, col_to_index, format_ref, index_to_col, key_to_addr, parse_ref


class Issue1MultiLetterColumnsTests(unittest.TestCase):
    def test_col_roundtrip_boundaries(self):
        cases = [
            (1, "A"),
            (26, "Z"),
            (27, "AA"),
            (52, "AZ"),
            (53, "BA"),
            (702, "ZZ"),
            (703, "AAA"),
            (18278, "ZZZ"),
        ]
        for idx, col in cases:
            self.assertEqual(index_to_col(idx), col)
            self.assertEqual(col_to_index(col), idx)
            self.assertEqual(col_to_index(col.lower()), idx)

        for idx in range(1, 2000):
            col = index_to_col(idx)
            self.assertEqual(col_to_index(col), idx)

    def test_sheet_wide_columns_and_ranges(self):
        s = Sheet()
        s.set("A1", 1)
        s.set("AA1", 100)
        s.set("ZZ10", 50)
        s.set("AAA1", 7)
        s.set("ZZZ99", 3)
        self.assertEqual(s.get("A1"), 1.0)
        self.assertEqual(s.get("AA1"), 100.0)
        self.assertEqual(s.get("AAA1"), 7.0)
        self.assertEqual(s.get("ZZZ99"), 3.0)

        s.set("Z1", 10)
        s.set("AB1", 20)
        s.set("AC1", "=SUM(Z1:AB1)+ZZZ99")
        self.assertEqual(s.get("AC1"), 133.0)
        s.set("AA1", 200)
        self.assertEqual(s.get("AC1"), 233.0)

        self.assertEqual(key_to_addr(addr_to_key("zz10")), "ZZ10")
        self.assertEqual(format_ref(parse_ref("$aa$5")), "$AA$5")


class Issue2PrecedenceTests(unittest.TestCase):
    def ev(self, formula):
        s = Sheet()
        s.set("A1", formula)
        return s.get("A1")

    def test_unary_and_power(self):
        self.assertEqual(self.ev("=-2^2"), -4.0)
        self.assertEqual(self.ev("=+2^2"), 4.0)
        self.assertEqual(self.ev("=--2^2"), 4.0)
        self.assertEqual(self.ev("=(-2)^2"), 4.0)
        self.assertEqual(self.ev("=2^3^2"), 512.0)
        self.assertEqual(self.ev("=2^-1"), 0.5)
        self.assertEqual(self.ev("=-2^-2"), -0.25)
        self.assertEqual(self.ev("=2^-2^2"), 0.0625)
        self.assertEqual(self.ev("=1-2^2"), -3.0)
        self.assertEqual(self.ev("=2*-3^2"), -18.0)

    def test_invalid_row_zero_raises_syntax_error(self):
        s = Sheet()
        with self.assertRaises(FormulaSyntaxError):
            s.set("A1", "=A0")


class Issue3RecalculationOrderTests(unittest.TestCase):
    def test_diamond_independent_of_coordinates(self):
        s = Sheet()
        s.set("A1", 1)
        s.set("B2", "=A1*2")
        s.set("C5", "=B2+1")
        s.set("A3", "=B2+C5")
        self.assertEqual(s.get("A3"), 5.0)
        s.set("A1", 10)
        self.assertEqual(s.get("B2"), 20.0)
        self.assertEqual(s.get("C5"), 21.0)
        self.assertEqual(s.get("A3"), 41.0)

    def test_deep_and_multi_path_dag(self):
        s = Sheet()
        s.set("Z10", 2)
        s.set("Y9", "=Z10+3")
        s.set("X8", "=Y9*2")
        s.set("A1", "=Z10+Y9+X8")
        s.set("B1", "=A1+X8")
        self.assertEqual(s.get("A1"), 17.0)
        self.assertEqual(s.get("B1"), 27.0)
        s.set("Z10", 5)
        self.assertEqual(s.get("Y9"), 8.0)
        self.assertEqual(s.get("X8"), 16.0)
        self.assertEqual(s.get("A1"), 29.0)
        self.assertEqual(s.get("B1"), 45.0)


class Issue4CycleCleanupTests(unittest.TestCase):
    def test_overwrite_formula_removes_old_deps(self):
        s = Sheet()
        s.set("A1", "=B1")
        s.set("A1", 1)
        s.set("B1", "=A1")
        self.assertEqual(s.get("B1"), 1.0)

    def test_break_real_cycle_updates_all_downstream(self):
        s = Sheet()
        s.set("A1", "=B1+1")
        s.set("B1", "=A1+1")
        s.set("C1", "=B1*10")
        self.assertEqual(s.get("A1"), ErrorValue("#CYCLE!"))
        self.assertEqual(s.get("B1"), ErrorValue("#CYCLE!"))
        self.assertEqual(s.get("C1"), ErrorValue("#CYCLE!"))

        s.set("A1", 5)
        self.assertEqual(s.get("A1"), 5.0)
        self.assertEqual(s.get("B1"), 6.0)
        self.assertEqual(s.get("C1"), 60.0)

    def test_clear_cell_breaks_cycle(self):
        s = Sheet()
        s.set("A1", "=B1")
        s.set("B1", "=A1+2")
        self.assertEqual(s.get("B1"), ErrorValue("#CYCLE!"))
        s.set("A1", None)
        self.assertIsNone(s.get("A1"))
        self.assertEqual(s.get("B1"), 2.0)

    def test_downstream_of_newly_created_cycle(self):
        s = Sheet()
        s.set("A1", 1)
        s.set("B1", "=A1")
        s.set("D1", "=B1+1")
        s.set("C1", "=B1")
        self.assertEqual(s.get("D1"), 2.0)
        # Introduce cycle B1 <-> C1 while updating B1
        s.set("B1", "=A1+C1")
        self.assertEqual(s.get("B1"), ErrorValue("#CYCLE!"))
        self.assertEqual(s.get("C1"), ErrorValue("#CYCLE!"))
        self.assertEqual(s.get("D1"), ErrorValue("#CYCLE!"))
        # Break cycle via C1
        s.set("C1", 4)
        self.assertEqual(s.get("B1"), 5.0)
        self.assertEqual(s.get("D1"), 6.0)

    def test_if_untaken_branch_in_cycle_downstream(self):
        s = Sheet()
        s.set("A1", 1)
        s.set("B1", "=C1")
        s.set("C1", "=B1")
        s.set("D1", "=IF(A1>0, 42, B1)")
        self.assertEqual(s.get("D1"), 42.0)
        s.set("A1", 0)
        self.assertEqual(s.get("D1"), ErrorValue("#CYCLE!"))


class Issue5AggregateRangeTests(unittest.TestCase):
    def test_sum_ignores_text_bool_empty_in_range(self):
        s = Sheet()
        s.set("B1", 1)
        s.set("B2", "n/a")
        s.set("B3", 2)
        s.set("B4", True)
        s.set("B5", False)
        # B6 empty
        s.set("C1", "=SUM(B1:B6)")
        s.set("C2", "=AVERAGE(B1:B6)")
        s.set("C3", "=MIN(B1:B6)")
        s.set("C4", "=MAX(B1:B6)")
        self.assertEqual(s.get("C1"), 3.0)
        self.assertEqual(s.get("C2"), 1.5)
        self.assertEqual(s.get("C3"), 1.0)
        self.assertEqual(s.get("C4"), 2.0)

    def test_empty_or_non_numeric_range_edge_cases(self):
        s = Sheet()
        s.set("A1", "hello")
        s.set("A2", True)
        s.set("B1", "=SUM(A1:A3)")
        s.set("B2", "=AVERAGE(A1:A3)")
        s.set("B3", "=MIN(A1:A3)")
        s.set("B4", "=MAX(A1:A3)")
        self.assertEqual(s.get("B1"), 0.0)
        self.assertEqual(s.get("B2"), ErrorValue("#DIV/0!"))
        self.assertEqual(s.get("B3"), 0.0)
        self.assertEqual(s.get("B4"), 0.0)

    def test_direct_args_vs_range_and_errors(self):
        s = Sheet()
        s.set("A1", "txt")
        s.set("A2", True)
        s.set("B1", "=SUM(A1:A2, TRUE)")
        self.assertEqual(s.get("B1"), 1.0)
        s.set("B2", "=SUM(A1)")
        self.assertEqual(s.get("B2"), ErrorValue("#VALUE!"))
        s.set("A3", "=1/0")
        s.set("B3", "=SUM(A1:A3)")
        self.assertEqual(s.get("B3"), ErrorValue("#DIV/0!"))


class Issue6CopyCellTests(unittest.TestCase):
    def test_copy_literal_and_empty(self):
        s = Sheet()
        s.set("A1", 42)
        s.set("A2", "hello")
        s.set("A3", True)
        s.set("A4", 0)
        s.set("A5", False)
        s.set("B1", 99)
        s.copy_cell("A1", "B1")
        s.copy_cell("A2", "B2")
        s.copy_cell("A3", "B3")
        s.copy_cell("A4", "B4")
        s.copy_cell("A5", "B5")
        self.assertEqual(s.get("B1"), 42.0)
        self.assertEqual(s.get("B2"), "hello")
        self.assertIs(s.get("B3"), True)
        self.assertEqual(s.get("B4"), 0.0)
        self.assertIs(s.get("B5"), False)

        s.copy_cell("Z9", "B1")
        self.assertIsNone(s.get("B1"))
        self.assertIsNone(s.get_content("B1"))

    def test_copy_formula_abs_and_rel(self):
        s = Sheet()
        s.set("A1", 10)
        s.set("B3", 5)
        s.set("B1", "=$A$1+A1+$A1+A$1")
        s.copy_cell("B1", "C3")
        self.assertEqual(s.get_formula("C3"), "=$A$1+B3+$A3+B$1")
        self.assertEqual(s.get("C3"), 10.0 + 5.0 + 0.0 + 40.0)

        # Same-cell copy canonicalizes lowercase refs
        s.set("D1", "=$a$1+b3")
        s.copy_cell("D1", "d1")
        self.assertEqual(s.get_formula("D1"), "=$A$1+B3")

    def test_copy_preserves_formatting_and_strings(self):
        s = Sheet()
        s.set("A1", 2)
        s.set("A2", 3)
        s.set("B1", '=  sum( a1 : $a2 ,  "A1""B2" ) & "" ')
        s.copy_cell("B1", "C2")
        self.assertEqual(
            s.get_formula("C2"),
            '=  sum( B2 : $A3 ,  "A1""B2" ) & "" ',
        )

    def test_copy_out_of_bounds_becomes_ref_error(self):
        s = Sheet()
        s.set("B2", "=A1+1")
        s.copy_cell("B2", "A1")
        self.assertEqual(s.get_formula("A1"), "=#REF!+1")
        self.assertEqual(s.get("A1"), ErrorValue("#REF!"))

        s.set("C3", "=SUM(A1:B2)+1")
        s.copy_cell("C3", "B3")
        self.assertEqual(s.get_formula("B3"), "=SUM(#REF!)+1")
        self.assertEqual(s.get("B3"), ErrorValue("#REF!"))

        s.set("C4", "=SUM(A1 : D4)")
        s.copy_cell("C4", "C1")
        self.assertEqual(s.get_formula("C1"), "=SUM(#REF!)")

    def test_copy_overwriting_and_recalculation(self):
        s = Sheet()
        s.set("A1", 10)
        s.set("B1", "=A1*2")
        s.set("C1", "=B1+5")
        self.assertEqual(s.get("C1"), 25.0)
        s.set("D1", 100)
        s.copy_cell("D1", "B1")
        self.assertEqual(s.get("B1"), 100.0)
        self.assertEqual(s.get("C1"), 105.0)

        # Copying past ZZZ turns out-of-range ref into #REF!
        s.set("A2", "=B2")
        s.copy_cell("A2", "ZZZ2")
        self.assertEqual(s.get_formula("ZZZ2"), "=#REF!")
        self.assertEqual(s.get("ZZZ2"), ErrorValue("#REF!"))


if __name__ == "__main__":
    unittest.main()
