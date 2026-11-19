import unittest

from cellcalc import ErrorValue, Sheet
from cellcalc.refs import col_to_index, index_to_col


class Issue1ColumnTests(unittest.TestCase):
    def test_col_conversions(self):
        self.assertEqual(col_to_index("A"), 1)
        self.assertEqual(col_to_index("Z"), 26)
        self.assertEqual(col_to_index("AA"), 27)
        self.assertEqual(col_to_index("AZ"), 52)
        self.assertEqual(col_to_index("BA"), 53)
        self.assertEqual(col_to_index("ZZ"), 702)
        self.assertEqual(col_to_index("AAA"), 703)
        self.assertEqual(col_to_index("ZZZ"), 18278)

        self.assertEqual(index_to_col(1), "A")
        self.assertEqual(index_to_col(26), "Z")
        self.assertEqual(index_to_col(27), "AA")
        self.assertEqual(index_to_col(52), "AZ")
        self.assertEqual(index_to_col(53), "BA")
        self.assertEqual(index_to_col(702), "ZZ")
        self.assertEqual(index_to_col(703), "AAA")
        self.assertEqual(index_to_col(18278), "ZZZ")

    def test_wide_sheet(self):
        s = Sheet()
        s.set("A1", 1)
        s.set("AA1", 100)
        s.set("ZZZ5", 42)
        s.set("AB1", "=A1+AA1+ZZZ5")
        self.assertEqual(s.get("A1"), 1.0)
        self.assertEqual(s.get("AA1"), 100.0)
        self.assertEqual(s.get("AB1"), 143.0)


class Issue2PrecedenceTests(unittest.TestCase):
    def ev(self, formula):
        s = Sheet()
        s.set("A1", formula)
        return s.get("A1")

    def test_power_and_unary(self):
        self.assertEqual(self.ev("=-2^2"), -4.0)
        self.assertEqual(self.ev("=2^3^2"), 512.0)
        self.assertEqual(self.ev("=2^-1"), 0.5)
        self.assertEqual(self.ev("=-2^-2"), -0.25)
        self.assertEqual(self.ev("=(-2)^2"), 4.0)
        self.assertEqual(self.ev("=+2^3"), 8.0)
        self.assertEqual(self.ev("=--2"), 2.0)


class Issue3TopoOrderTests(unittest.TestCase):
    def test_diamond_and_order(self):
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


class Issue4CycleCleanupTests(unittest.TestCase):
    def test_overwrite_clears_old_deps(self):
        s = Sheet()
        s.set("A1", "=B1")
        s.set("A1", 1)
        s.set("B1", "=A1")
        self.assertEqual(s.get("B1"), 1.0)

    def test_break_real_cycle(self):
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

    def test_clear_breaks_cycle(self):
        s = Sheet()
        s.set("A1", "=B1+1")
        s.set("B1", "=A1+2")
        s.set("A1", None)
        self.assertIsNone(s.get("A1"))
        self.assertEqual(s.get("B1"), 2.0)


class Issue5AggregateRangeTests(unittest.TestCase):
    def test_range_ignores_text_and_bool(self):
        s = Sheet()
        s.set("B1", 1)
        s.set("B2", "n/a")
        s.set("B3", 2)
        s.set("B4", True)
        s.set("C1", "=SUM(B1:B5)")
        s.set("C2", "=AVERAGE(B1:B5)")
        s.set("C3", "=MIN(B1:B5)")
        s.set("C4", "=MAX(B1:B5)")
        self.assertEqual(s.get("C1"), 3.0)
        self.assertEqual(s.get("C2"), 1.5)
        self.assertEqual(s.get("C3"), 1.0)
        self.assertEqual(s.get("C4"), 2.0)

    def test_direct_args_still_coerced(self):
        s = Sheet()
        s.set("A1", "=SUM(1, TRUE)")
        s.set("A2", '=SUM(1, "bad")')
        self.assertEqual(s.get("A1"), 2.0)
        self.assertEqual(s.get("A2"), ErrorValue("#VALUE!"))

    def test_empty_numeric_range_aggregates(self):
        s = Sheet()
        s.set("A1", "txt")
        s.set("A2", False)
        s.set("B1", "=AVERAGE(A1:A3)")
        s.set("B2", "=MIN(A1:A3)")
        s.set("B3", "=MAX(A1:A3)")
        self.assertEqual(s.get("B1"), ErrorValue("#DIV/0!"))
        self.assertEqual(s.get("B2"), 0.0)
        self.assertEqual(s.get("B3"), 0.0)


class Issue6CopyCellTests(unittest.TestCase):
    def test_copy_literal_and_empty(self):
        s = Sheet()
        s.set("A1", 42)
        s.copy_cell("A1", "B2")
        self.assertEqual(s.get("B2"), 42.0)
        s.copy_cell("Z9", "B2")
        self.assertIsNone(s.get("B2"))

    def test_copy_formula_abs_rel_and_formatting(self):
        s = Sheet()
        s.set("A1", 10)
        s.set("B2", 20)
        s.set("B1", "=$A$1+a1 + $a1 + A$1")
        s.copy_cell("B1", "C3")
        self.assertEqual(s.get_formula("C3"), "=$A$1+B3 + $A3 + B$1")

        s.set("D1", '=sum( a1:b2 ) & "A1"')
        s.copy_cell("D1", "E2")
        self.assertEqual(s.get_formula("E2"), '=sum( B2:C3 ) & "A1"')

    def test_copy_out_of_bounds_becomes_ref_error(self):
        s = Sheet()
        s.set("B2", "=A1+1")
        s.copy_cell("B2", "A1")
        self.assertEqual(s.get_formula("A1"), "=#REF!+1")
        self.assertEqual(s.get("A1"), ErrorValue("#REF!"))

        s.set("B2", "=SUM(A1:B2)+5")
        s.copy_cell("B2", "A2")
        self.assertEqual(s.get_formula("A2"), "=SUM(#REF!)+5")
        self.assertEqual(s.get("A2"), ErrorValue("#REF!"))


if __name__ == "__main__":
    unittest.main()
