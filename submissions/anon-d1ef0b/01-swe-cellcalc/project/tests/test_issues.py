import unittest

from cellcalc import ErrorValue, FormulaSyntaxError, Sheet
from cellcalc.refs import (
    CellRef,
    addr_to_key,
    col_to_index,
    format_ref,
    index_to_col,
    key_to_addr,
    parse_ref,
)


class Issue1ColumnsAfterZTests(unittest.TestCase):
    def test_col_conversions_exhaustive_boundaries(self):
        cases = [
            ("A", 1),
            ("B", 2),
            ("Z", 26),
            ("AA", 27),
            ("AB", 28),
            ("AZ", 52),
            ("BA", 53),
            ("ZZ", 702),
            ("AAA", 703),
            ("AAB", 704),
            ("AAZ", 728),
            ("ABA", 729),
            ("AZZ", 1378),
            ("BAA", 1379),
            ("ZZZ", 18278),
        ]
        for letters, idx in cases:
            self.assertEqual(col_to_index(letters), idx)
            self.assertEqual(col_to_index(letters.lower()), idx)
            self.assertEqual(index_to_col(idx), letters)

    def test_bijection_all_3_letter_columns(self):
        for idx in range(1, 18279):
            col = index_to_col(idx)
            self.assertEqual(col_to_index(col), idx)

    def test_sheet_wide_columns_and_ranges(self):
        s = Sheet()
        s.set("A1", 1)
        s.set("Z1", 26)
        s.set("AA1", 100)
        s.set("AB1", 200)
        s.set("ZZ1", 702)
        s.set("AAA1", 703)
        s.set("ZZZ1", 999)
        self.assertEqual(s.get("A1"), 1.0)
        self.assertEqual(s.get("Z1"), 26.0)
        self.assertEqual(s.get("AA1"), 100.0)
        self.assertEqual(s.get("ZZZ1"), 999.0)

        s.set("ZZZ2", "=SUM(Z1:AB1)")
        self.assertEqual(s.get("ZZZ2"), 326.0)

        s.set("AAA2", "=ZZ1+AAA1+ZZZ1")
        self.assertEqual(s.get("AAA2"), 2404.0)

        self.assertEqual(key_to_addr(addr_to_key("AZ10")), "AZ10")
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
        self.assertEqual(self.ev("=---2^2"), -4.0)
        self.assertEqual(self.ev("=(-2)^2"), 4.0)
        self.assertEqual(self.ev("=2^3^2"), 512.0)
        self.assertEqual(self.ev("=2^-1"), 0.5)
        self.assertEqual(self.ev("=2^+3"), 8.0)
        self.assertEqual(self.ev("=2^-3^2"), 2.0 ** -9)
        self.assertEqual(self.ev("=-2^3^2"), -512.0)
        self.assertEqual(self.ev("=-2^3*4"), -32.0)
        self.assertEqual(self.ev("=3*-2^2"), -12.0)
        self.assertEqual(self.ev("=10-2^3"), 2.0)
        self.assertEqual(self.ev("=2^-1*4"), 2.0)
        self.assertEqual(self.ev("=4^0.5"), 2.0)
        self.assertEqual(self.ev("=2^3^2^1"), 512.0)

    def test_invalid_row_zero_is_syntax_error(self):
        s = Sheet()
        with self.assertRaises(FormulaSyntaxError):
            s.set("A1", "=A0+1")


class Issue3TopologicalRecalcTests(unittest.TestCase):
    def test_diamond_repro(self):
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

    def test_deep_multi_diamond_dag(self):
        s = Sheet()
        s.set("Z1", 1)
        s.set("Y1", "=Z1+1")
        s.set("X1", "=Y1+Z1")
        s.set("W1", "=X1+Y1+Z1")
        s.set("A1", "=W1+X1+Y1+Z1")
        self.assertEqual(s.get("A1"), 12.0)

        s.set("Z1", 10)
        # Z1=10, Y1=11, X1=21, W1=42, A1=84
        self.assertEqual(s.get("Y1"), 11.0)
        self.assertEqual(s.get("X1"), 21.0)
        self.assertEqual(s.get("W1"), 42.0)
        self.assertEqual(s.get("A1"), 84.0)

    def test_recalc_with_cycle_and_downstream(self):
        s = Sheet()
        s.set("A1", 5)
        s.set("B1", "=A1+C1")
        s.set("C1", "=B1")
        s.set("A2", "=C1+10")
        s.set("A3", "=A1+A2")
        self.assertEqual(s.get("B1"), ErrorValue("#CYCLE!"))
        self.assertEqual(s.get("C1"), ErrorValue("#CYCLE!"))
        self.assertEqual(s.get("A2"), ErrorValue("#CYCLE!"))
        self.assertEqual(s.get("A3"), ErrorValue("#CYCLE!"))

        # Edit A1: cycle stays cycle, downstream stays cycle
        s.set("A1", 10)
        self.assertEqual(s.get("A3"), ErrorValue("#CYCLE!"))

        # Break cycle at C1
        s.set("C1", 2)
        self.assertEqual(s.get("B1"), 12.0)
        self.assertEqual(s.get("A2"), 12.0)
        self.assertEqual(s.get("A3"), 22.0)


class Issue4StaleDepsAndCycleRecoveryTests(unittest.TestCase):
    def test_stale_dep_repro(self):
        s = Sheet()
        s.set("A1", "=B1")
        s.set("A1", 1)
        s.set("B1", "=A1")
        self.assertEqual(s.get("B1"), 1.0)

    def test_break_real_two_cell_cycle(self):
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

    def test_break_cycle_by_clearing(self):
        s = Sheet()
        s.set("A1", "=B1+1")
        s.set("B1", "=C1+1")
        s.set("C1", "=A1+1")
        self.assertEqual(s.get("A1"), ErrorValue("#CYCLE!"))
        s.set("B1", None)
        self.assertIsNone(s.get("B1"))
        self.assertEqual(s.get("A1"), 1.0)
        self.assertEqual(s.get("C1"), 2.0)

    def test_break_self_cycle(self):
        s = Sheet()
        s.set("A1", "=A1+1")
        self.assertEqual(s.get("A1"), ErrorValue("#CYCLE!"))
        s.set("A1", 42)
        self.assertEqual(s.get("A1"), 42.0)
        s.set("B1", "=A1")
        self.assertEqual(s.get("B1"), 42.0)

    def test_retarget_formula_forgets_old_deps(self):
        s = Sheet()
        s.set("A1", 1)
        s.set("B1", 10)
        s.set("C1", "=A1")
        self.assertEqual(s.get("C1"), 1.0)
        s.set("C1", "=B1")
        self.assertEqual(s.get("C1"), 10.0)
        # Making A1 depend on C1 must not form a cycle
        s.set("A1", "=C1+1")
        self.assertEqual(s.get("A1"), 11.0)
        self.assertEqual(s.get("C1"), 10.0)

    def test_invalid_formula_does_not_corrupt_deps(self):
        s = Sheet()
        s.set("A1", 2)
        s.set("B1", "=A1*3")
        with self.assertRaises(FormulaSyntaxError):
            s.set("B1", "=1+")
        s.set("A1", 5)
        self.assertEqual(s.get("B1"), 15.0)


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

    def test_no_numbers_in_range(self):
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

    def test_direct_args_coerced(self):
        s = Sheet()
        s.set("A1", 10)
        s.set("A2", "text")
        s.set("A3", True)
        s.set("B1", "=SUM(A1, A3)")
        s.set("B2", "=SUM(A1, A2)")
        s.set("B3", "=SUM(A1:A3, TRUE)")
        self.assertEqual(s.get("B1"), 11.0)
        self.assertEqual(s.get("B2"), ErrorValue("#VALUE!"))
        self.assertEqual(s.get("B3"), 11.0)

    def test_error_in_range_propagates(self):
        s = Sheet()
        s.set("A1", "text")
        s.set("A2", "=1/0")
        s.set("A3", 5)
        s.set("B1", "=SUM(A1:A3)")
        s.set("B2", "=MIN(A1:A3)")
        self.assertEqual(s.get("B1"), ErrorValue("#DIV/0!"))
        self.assertEqual(s.get("B2"), ErrorValue("#DIV/0!"))


class Issue6CopyCellTests(unittest.TestCase):
    def test_copy_literals_and_empty(self):
        s = Sheet()
        s.set("A1", 42)
        s.set("A2", "hello")
        s.set("A3", True)
        s.set("B4", 99)

        s.copy_cell("A1", "B1")
        s.copy_cell("A2", "B2")
        s.copy_cell("A3", "B3")
        s.copy_cell("A4", "B4")  # A4 empty -> clears B4

        self.assertEqual(s.get("B1"), 42.0)
        self.assertEqual(s.get("B2"), "hello")
        self.assertIs(s.get("B3"), True)
        self.assertIsNone(s.get("B4"))
        self.assertIsNone(s.get_content("B4"))

    def test_copy_formula_absolute_and_relative(self):
        s = Sheet()
        s.set("A1", 10)
        s.set("B3", 5)
        s.set("B1", "=$A$1+A1")
        s.copy_cell("B1", "C3")
        self.assertEqual(s.get_formula("C3"), "=$A$1+B3")
        self.assertEqual(s.get("C3"), 15.0)

    def test_copy_formula_mixed_anchors(self):
        s = Sheet()
        s.set("C3", "=$A1+A$1+$A$1+A1")
        s.copy_cell("C3", "E6")  # +2 col, +3 row
        self.assertEqual(s.get_formula("E6"), "=$A4+C$1+$A$1+C4")

    def test_copy_preserves_formatting_and_strings(self):
        s = Sheet()
        s.set("B2", '=sum( a1 : $b$2 , "A1" ) & "a1:b2" & "say ""A1"""')
        s.copy_cell("B2", "C4")  # +1 col, +2 row
        self.assertEqual(
            s.get_formula("C4"),
            '=sum( B3 : $B$2 , "A1" ) & "a1:b2" & "say ""A1"""',
        )

    def test_copy_ref_out_of_bounds_single(self):
        s = Sheet()
        s.set("B2", "=A1+1")
        s.copy_cell("B2", "A1")
        self.assertEqual(s.get_formula("A1"), "=#REF!+1")
        self.assertEqual(s.get("A1"), ErrorValue("#REF!"))

    def test_copy_ref_out_of_bounds_range(self):
        s = Sheet()
        s.set("B2", "=SUM(A1:B2)+C3")
        s.copy_cell("B2", "A2")  # -1 col, 0 row -> A1 out of bounds, B2 ok, C3->B3
        self.assertEqual(s.get_formula("A2"), "=SUM(#REF!)+B3")
        self.assertEqual(s.get("A2"), ErrorValue("#REF!"))

    def test_copy_ref_out_of_bounds_range_with_spaces(self):
        s = Sheet()
        s.set("B2", "=SUM( A1 : B2 )")
        s.copy_cell("B2", "B1")  # 0 col, -1 row -> A1 out of bounds
        self.assertEqual(s.get_formula("B1"), "=SUM( #REF! )")
        self.assertEqual(s.get("B1"), ErrorValue("#REF!"))

    def test_copy_ref_across_z_and_past_zzz(self):
        s = Sheet()
        s.set("A1", "=Z1+ZZ1")
        s.copy_cell("A1", "B1")  # +1 col
        self.assertEqual(s.get_formula("B1"), "=AA1+AAA1")

        s.set("A2", "=ZZZ1+1")
        s.copy_cell("A2", "B2")  # +1 col -> past ZZZ
        self.assertEqual(s.get_formula("B2"), "=#REF!+1")
        self.assertEqual(s.get("B2"), ErrorValue("#REF!"))

    def test_copy_triggers_recalculation_and_deps(self):
        s = Sheet()
        s.set("A1", 2)
        s.set("A2", 5)
        s.set("B1", "=A1*10")
        s.set("C2", "=B2+1")
        s.copy_cell("B1", "B2")
        self.assertEqual(s.get_formula("B2"), "=A2*10")
        self.assertEqual(s.get("B2"), 50.0)
        self.assertEqual(s.get("C2"), 51.0)
        # Updating A2 propagates through copied B2 to C2
        s.set("A2", 7)
        self.assertEqual(s.get("B2"), 70.0)
        self.assertEqual(s.get("C2"), 71.0)

    def test_copy_onto_self(self):
        s = Sheet()
        s.set("B2", "=a1+1")
        s.copy_cell("B2", "B2")
        self.assertEqual(s.get_formula("B2"), "=A1+1")


if __name__ == "__main__":
    unittest.main()
