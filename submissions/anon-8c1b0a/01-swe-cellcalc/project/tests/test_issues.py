import unittest

from cellcalc import ErrorValue, Sheet
from cellcalc.refs import col_to_index, index_to_col, parse_ref


class Issue1ColumnTests(unittest.TestCase):
    def test_col_index_roundtrip(self):
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
            self.assertEqual(col_to_index(index_to_col(idx)), idx)

    def test_sheet_wide_columns(self):
        s = Sheet()
        s.set("A1", 1)
        s.set("Z1", 26)
        s.set("AA1", 100)
        s.set("AZ1", 200)
        s.set("ZZ1", 300)
        s.set("AAA1", 400)
        s.set("ZZZ1", 500)
        self.assertEqual(s.get("A1"), 1.0)
        self.assertEqual(s.get("Z1"), 26.0)
        self.assertEqual(s.get("AA1"), 100.0)
        self.assertEqual(s.get("AZ1"), 200.0)
        self.assertEqual(s.get("ZZ1"), 300.0)
        self.assertEqual(s.get("AAA1"), 400.0)
        self.assertEqual(s.get("ZZZ1"), 500.0)

        s.set("B1", "=SUM(Z1:AA1) + AAA1 + ZZZ1")
        self.assertEqual(s.get("B1"), 1026.0)


class Issue2PrecedenceTests(unittest.TestCase):
    def ev(self, formula: str):
        s = Sheet()
        s.set("A1", formula)
        return s.get("A1")

    def test_power_and_unary(self):
        self.assertEqual(self.ev("=-2^2"), -4.0)
        self.assertEqual(self.ev("=+2^2"), 4.0)
        self.assertEqual(self.ev("=(-2)^2"), 4.0)
        self.assertEqual(self.ev("=--2^2"), 4.0)
        self.assertEqual(self.ev("=2^3^2"), 512.0)
        self.assertEqual(self.ev("=(2^3)^2"), 64.0)
        self.assertEqual(self.ev("=2^-1"), 0.5)
        self.assertEqual(self.ev("=2^+1"), 2.0)
        self.assertEqual(self.ev("=-2^-2"), -0.25)
        self.assertEqual(self.ev("=2^-3^2"), 2.0 ** -9)
        self.assertEqual(self.ev("=2^-1*4"), 2.0)
        self.assertEqual(self.ev("=4*-2^2"), -16.0)
        self.assertEqual(self.ev("=10-2^2"), 6.0)


class Issue3RecalcOrderTests(unittest.TestCase):
    def test_diamond_dependency_order(self):
        s = Sheet()
        s.set("A1", 1)
        s.set("B2", "=A1*2")
        s.set("C5", "=B2+1")
        s.set("A3", "=B2+C5")
        self.assertEqual(s.get("A3"), 5.0)
        s.set("A1", 10)
        self.assertEqual(s.get("A3"), 41.0)

    def test_deep_dag_reverse_coords(self):
        s = Sheet()
        s.set("Z10", 2)
        s.set("M5", "=Z10 * 3")
        s.set("D4", "=M5 + Z10")
        s.set("B2", "=D4 * M5")
        s.set("A1", "=B2 + D4 + M5 + Z10")
        self.assertEqual(s.get("A1"), 48.0 + 8.0 + 6.0 + 2.0)
        s.set("Z10", 5)
        # M5 = 15, D4 = 20, B2 = 300, A1 = 300 + 20 + 15 + 5 = 340
        self.assertEqual(s.get("A1"), 340.0)


class Issue4CycleRecoveryTests(unittest.TestCase):
    def test_overwrite_before_cycle(self):
        s = Sheet()
        s.set("A1", "=B1")
        s.set("A1", 1)
        s.set("B1", "=A1")
        self.assertEqual(s.get("B1"), 1.0)

    def test_break_two_cell_cycle_with_literal(self):
        s = Sheet()
        s.set("A1", "=B1+1")
        s.set("B1", "=A1+1")
        s.set("C1", "=B1*2")
        self.assertEqual(s.get("A1"), ErrorValue("#CYCLE!"))
        self.assertEqual(s.get("B1"), ErrorValue("#CYCLE!"))
        self.assertEqual(s.get("C1"), ErrorValue("#CYCLE!"))

        s.set("A1", 10)
        self.assertEqual(s.get("A1"), 10.0)
        self.assertEqual(s.get("B1"), 11.0)
        self.assertEqual(s.get("C1"), 22.0)

    def test_break_cycle_with_formula_or_clear(self):
        s = Sheet()
        s.set("A1", "=B1")
        s.set("B1", "=C1")
        s.set("C1", "=A1")
        self.assertEqual(s.get("A1"), ErrorValue("#CYCLE!"))
        self.assertEqual(s.get("B1"), ErrorValue("#CYCLE!"))
        self.assertEqual(s.get("C1"), ErrorValue("#CYCLE!"))

        s.set("C1", "=5+5")
        self.assertEqual(s.get("C1"), 10.0)
        self.assertEqual(s.get("B1"), 10.0)
        self.assertEqual(s.get("A1"), 10.0)

        # Re-introduce self-cycle and then clear it
        s.set("C1", "=C1+1")
        self.assertEqual(s.get("C1"), ErrorValue("#CYCLE!"))
        self.assertEqual(s.get("A1"), ErrorValue("#CYCLE!"))
        s.set("C1", None)
        self.assertIsNone(s.get("C1"))
        self.assertIsNone(s.get("B1"))
        self.assertIsNone(s.get("A1"))


class Issue5RangeAggregateTests(unittest.TestCase):
    def test_range_ignores_text_and_bool_and_empty(self):
        s = Sheet()
        s.set("B1", 1)
        s.set("B2", "n/a")
        s.set("B3", 2)
        s.set("B4", True)
        s.set("B5", False)
        s.set("C1", "=SUM(B1:B6)")
        s.set("C2", "=AVERAGE(B1:B6)")
        s.set("C3", "=MIN(B1:B6)")
        s.set("C4", "=MAX(B1:B6)")
        self.assertEqual(s.get("C1"), 3.0)
        self.assertEqual(s.get("C2"), 1.5)
        self.assertEqual(s.get("C3"), 1.0)
        self.assertEqual(s.get("C4"), 2.0)

    def test_empty_numeric_range_aggregates(self):
        s = Sheet()
        s.set("A1", "text")
        s.set("A2", True)
        s.set("B1", "=SUM(A1:A3)")
        s.set("B2", "=AVERAGE(A1:A3)")
        s.set("B3", "=MIN(A1:A3)")
        s.set("B4", "=MAX(A1:A3)")
        self.assertEqual(s.get("B1"), 0.0)
        self.assertEqual(s.get("B2"), ErrorValue("#DIV/0!"))
        self.assertEqual(s.get("B3"), 0.0)
        self.assertEqual(s.get("B4"), 0.0)

    def test_direct_args_still_coerced(self):
        s = Sheet()
        s.set("B1", 1)
        s.set("B2", True)
        s.set("C1", "=SUM(B1:B2, TRUE)")
        s.set("C2", '=SUM(B1:B2, "n/a")')
        self.assertEqual(s.get("C1"), 2.0)
        self.assertEqual(s.get("C2"), ErrorValue("#VALUE!"))


class Issue6CopyCellTests(unittest.TestCase):
    def test_copy_literals_and_empty(self):
        s = Sheet()
        s.set("A1", 42)
        s.set("A2", "hello")
        s.set("A3", True)
        s.copy_cell("A1", "B1")
        s.copy_cell("A2", "B2")
        s.copy_cell("A3", "B3")
        self.assertEqual(s.get("B1"), 42.0)
        self.assertEqual(s.get("B2"), "hello")
        self.assertIs(s.get("B3"), True)

        # Copying empty cell clears destination and updates dependents
        s.set("C1", "=B1+1")
        self.assertEqual(s.get("C1"), 43.0)
        s.copy_cell("Z9", "B1")
        self.assertIsNone(s.get("B1"))
        self.assertIsNone(s.get_content("B1"))
        self.assertEqual(s.get("C1"), 1.0)

    def test_copy_formula_relative_and_absolute(self):
        s = Sheet()
        s.set("A1", 100)
        s.set("B3", 7)
        s.set("B1", "=$A$1+A1+$A1+A$1")
        s.copy_cell("B1", "C3")
        self.assertEqual(s.get_formula("C3"), "=$A$1+B3+$A3+B$1")
        self.assertEqual(s.get("C3"), 507.0)

    def test_copy_formula_preserves_formatting_and_canonicalizes_refs(self):
        s = Sheet()
        s.set("A1", '=sum( a1:b2 , "a1:b2" , $c3 ) + 1')
        s.copy_cell("A1", "B3")
        self.assertEqual(s.get_formula("B3"), '=sum( B3:C4 , "a1:b2" , $C5 ) + 1')

    def test_copy_formula_out_of_bounds_ref_and_range(self):
        s = Sheet()
        s.set("B2", "=A1+1")
        s.copy_cell("B2", "A1")
        self.assertEqual(s.get_formula("A1"), "=#REF!+1")
        self.assertEqual(s.get("A1"), ErrorValue("#REF!"))

        s.set("B2", "=SUM(A1:C3)+D4")
        s.copy_cell("B2", "A2")
        self.assertEqual(s.get_formula("A2"), "=SUM(#REF!)+C4")
        self.assertEqual(s.get("A2"), ErrorValue("#REF!"))


if __name__ == "__main__":
    unittest.main()
