import unittest

from cellcalc import ErrorValue, Sheet
from cellcalc.refs import col_to_index, index_to_col, parse_ref


class Issue1ColumnsTests(unittest.TestCase):
    def test_col_roundtrip(self):
        cases = [
            ("A", 1),
            ("Z", 26),
            ("AA", 27),
            ("AB", 28),
            ("AZ", 52),
            ("BA", 53),
            ("ZZ", 702),
            ("AAA", 703),
            ("XFD", 16384),
            ("ZZZ", 18278),
        ]
        for letters, idx in cases:
            self.assertEqual(col_to_index(letters), idx)
            self.assertEqual(index_to_col(idx), letters)

        # Exhaustive check across 1..2000 and boundary around ZZZ
        for i in range(1, 2000):
            c = index_to_col(i)
            self.assertEqual(col_to_index(c), i)
        for i in range(18270, 18279):
            c = index_to_col(i)
            self.assertEqual(col_to_index(c), i)

    def test_sheet_wide_columns(self):
        s = Sheet()
        s.set("A1", 1)
        s.set("Z1", 26)
        s.set("AA1", 100)
        s.set("AZ1", 52)
        s.set("ZZ1", 702)
        s.set("AAA1", 703)
        s.set("ZZZ1", 999)
        self.assertEqual(s.get("A1"), 1.0)
        self.assertEqual(s.get("Z1"), 26.0)
        self.assertEqual(s.get("AA1"), 100.0)
        self.assertEqual(s.get("AZ1"), 52.0)
        self.assertEqual(s.get("ZZ1"), 702.0)
        self.assertEqual(s.get("AAA1"), 703.0)
        self.assertEqual(s.get("ZZZ1"), 999.0)

        s.set("AA2", "=SUM(Z1:AA1)")
        self.assertEqual(s.get("AA2"), 126.0)


class Issue2PrecedenceTests(unittest.TestCase):
    def ev(self, formula):
        s = Sheet()
        s.set("A1", formula)
        return s.get("A1")

    def test_power_precedence_and_associativity(self):
        self.assertEqual(self.ev("=-2^2"), -4.0)
        self.assertEqual(self.ev("=(-2)^2"), 4.0)
        self.assertEqual(self.ev("=2^3^2"), 512.0)
        self.assertEqual(self.ev("=(2^3)^2"), 64.0)
        self.assertEqual(self.ev("=2^-1"), 0.5)
        self.assertEqual(self.ev("=-2^-2"), -0.25)
        self.assertEqual(self.ev("=2^-3^2"), 2.0 ** -9)
        self.assertEqual(self.ev("=+2^3"), 8.0)
        self.assertEqual(self.ev("=--2^2"), 4.0)
        self.assertEqual(self.ev("=2*3^2"), 18.0)
        self.assertEqual(self.ev("=-3*2"), -6.0)
        self.assertEqual(self.ev("=1-2^2"), -3.0)


class Issue3RecalcOrderTests(unittest.TestCase):
    def test_diamond_recalc(self):
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

    def test_deep_multi_path_dag(self):
        s = Sheet()
        s.set("Z1", 1)
        s.set("Y1", "=Z1+1")
        s.set("X1", "=Y1+1")
        s.set("W1", "=X1+1")
        s.set("A1", "=Z1+Y1+X1+W1")
        self.assertEqual(s.get("A1"), 10.0)
        s.set("Z1", 10)
        self.assertEqual(s.get("A1"), 46.0)


class Issue4StaleCycleTests(unittest.TestCase):
    def test_forgotten_old_reference(self):
        s = Sheet()
        s.set("A1", "=B1")
        s.set("A1", 1)
        s.set("B1", "=A1")
        self.assertEqual(s.get("B1"), 1.0)

    def test_break_two_cell_cycle(self):
        s = Sheet()
        s.set("A1", "=B1+1")
        s.set("B1", "=A1+1")
        s.set("C1", "=B1*2")
        self.assertEqual(s.get("A1"), ErrorValue("#CYCLE!"))
        self.assertEqual(s.get("B1"), ErrorValue("#CYCLE!"))
        self.assertEqual(s.get("C1"), ErrorValue("#CYCLE!"))
        s.set("A1", 5)
        self.assertEqual(s.get("A1"), 5.0)
        self.assertEqual(s.get("B1"), 6.0)
        self.assertEqual(s.get("C1"), 12.0)

    def test_clear_cell_breaks_cycle(self):
        s = Sheet()
        s.set("A1", "=B1")
        s.set("B1", "=A1+1")
        self.assertEqual(s.get("B1"), ErrorValue("#CYCLE!"))
        s.set("A1", None)
        self.assertIsNone(s.get("A1"))
        self.assertEqual(s.get("B1"), 1.0)


class Issue5AggregateRangeTests(unittest.TestCase):
    def test_sum_avg_min_max_ignore_text_and_bool_in_range(self):
        s = Sheet()
        s.set("B1", 1)
        s.set("B2", "n/a")
        s.set("B3", 2)
        s.set("B4", True)
        s.set("B5", False)
        # B6 is empty
        s.set("C1", "=SUM(B1:B6)")
        s.set("C2", "=AVERAGE(B1:B6)")
        s.set("C3", "=MIN(B1:B6)")
        s.set("C4", "=MAX(B1:B6)")
        self.assertEqual(s.get("C1"), 3.0)
        self.assertEqual(s.get("C2"), 1.5)
        self.assertEqual(s.get("C3"), 1.0)
        self.assertEqual(s.get("C4"), 2.0)

    def test_direct_args_still_coerce(self):
        s = Sheet()
        s.set("A1", "=SUM(1, TRUE)")
        s.set("A2", '=SUM(1, "text")')
        self.assertEqual(s.get("A1"), 2.0)
        self.assertEqual(s.get("A2"), ErrorValue("#VALUE!"))

    def test_no_numbers_in_range(self):
        s = Sheet()
        s.set("B1", "x")
        s.set("B2", True)
        s.set("C1", "=SUM(B1:B2)")
        s.set("C2", "=AVERAGE(B1:B2)")
        s.set("C3", "=MIN(B1:B2)")
        s.set("C4", "=MAX(B1:B2)")
        self.assertEqual(s.get("C1"), 0.0)
        self.assertEqual(s.get("C2"), ErrorValue("#DIV/0!"))
        self.assertEqual(s.get("C3"), 0.0)
        self.assertEqual(s.get("C4"), 0.0)

    def test_error_in_range_propagates(self):
        s = Sheet()
        s.set("B1", 1)
        s.set("B2", "=1/0")
        s.set("B3", "text")
        s.set("C1", "=SUM(B1:B3)")
        self.assertEqual(s.get("C1"), ErrorValue("#DIV/0!"))


class Issue6CopyCellTests(unittest.TestCase):
    def test_copy_literal_and_empty(self):
        s = Sheet()
        s.set("A1", 42)
        s.copy_cell("A1", "B2")
        self.assertEqual(s.get("B2"), 42.0)
        s.set("A2", "hello")
        s.copy_cell("A2", "B2")
        self.assertEqual(s.get("B2"), "hello")
        s.copy_cell("Z9", "B2")
        self.assertIsNone(s.get("B2"))
        self.assertIsNone(s.get_content("B2"))

    def test_copy_formula_relative_and_absolute(self):
        s = Sheet()
        s.set("A1", 10)
        s.set("B3", 5)
        s.set("B1", "=$A$1+A1")
        s.copy_cell("B1", "C3")
        self.assertEqual(s.get_formula("C3"), "=$A$1+B3")
        self.assertEqual(s.get("C3"), 15.0)

        s.set("B1", "=$a1 + a$1")
        s.copy_cell("B1", "D4")
        self.assertEqual(s.get_formula("D4"), "=$A4 + C$1")

    def test_copy_preserves_formatting_and_strings(self):
        s = Sheet()
        s.set("B2", '=  sum( a1:b1 ) & "A1" & "  b2:c3  "')
        s.copy_cell("B2", "C3")
        self.assertEqual(
            s.get_formula("C3"),
            '=  sum( B2:C2 ) & "A1" & "  b2:c3  "',
        )

    def test_copy_out_of_bounds_ref_and_range(self):
        s = Sheet()
        s.set("B2", "=A1+1")
        s.copy_cell("B2", "A1")
        self.assertEqual(s.get_formula("A1"), "=#REF!+1")
        self.assertEqual(s.get("A1"), ErrorValue("#REF!"))

        s.set("C3", "=SUM(B2:D4)+1")
        s.copy_cell("C3", "B2")
        self.assertEqual(s.get_formula("B2"), "=SUM(A1:C3)+1")

        s.copy_cell("C3", "A3")
        self.assertEqual(s.get_formula("A3"), "=SUM(#REF!)+1")
        self.assertEqual(s.get("A3"), ErrorValue("#REF!"))

    def test_copy_updates_dependents(self):
        s = Sheet()
        s.set("A1", 1)
        s.set("A2", 2)
        s.set("B1", "=A1*10")
        s.set("C2", "=B2+1")
        self.assertEqual(s.get("C2"), 1.0)
        s.copy_cell("B1", "B2")
        self.assertEqual(s.get_formula("B2"), "=A2*10")
        self.assertEqual(s.get("B2"), 20.0)
        self.assertEqual(s.get("C2"), 21.0)


if __name__ == "__main__":
    unittest.main()
