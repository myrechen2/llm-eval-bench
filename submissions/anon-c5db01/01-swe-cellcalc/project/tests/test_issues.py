import unittest

from cellcalc import ErrorValue, FormulaSyntaxError, Sheet
from cellcalc.refs import col_to_index, index_to_col


class Issue1MultiLetterColumnsTests(unittest.TestCase):
    def test_col_conversions(self):
        cases = [
            ("A", 1),
            ("Z", 26),
            ("AA", 27),
            ("AZ", 52),
            ("BA", 53),
            ("ZZ", 702),
            ("AAA", 703),
            ("ZZZ", 18278),
        ]
        for letters, idx in cases:
            self.assertEqual(col_to_index(letters), idx)
            self.assertEqual(col_to_index(letters.lower()), idx)
            self.assertEqual(index_to_col(idx), letters)

    def test_sheet_wide_columns(self):
        s = Sheet()
        s.set("A1", 1)
        s.set("AA1", 100)
        s.set("AZ5", 50)
        s.set("ZZZ9", 7)
        self.assertEqual(s.get("A1"), 1.0)
        self.assertEqual(s.get("AA1"), 100.0)
        s.set("AB1", "=AA1+AZ5+ZZZ9")
        self.assertEqual(s.get("AB1"), 157.0)
        s.set("AC1", "=SUM(Z1:AB1)")
        self.assertEqual(s.get("AC1"), 257.0)


class Issue2PrecedenceTests(unittest.TestCase):
    def ev(self, formula):
        s = Sheet()
        s.set("A1", formula)
        return s.get("A1")

    def test_unary_and_power(self):
        self.assertEqual(self.ev("=-2^2"), -4.0)
        self.assertEqual(self.ev("=(-2)^2"), 4.0)
        self.assertEqual(self.ev("=2^3^2"), 512.0)
        self.assertEqual(self.ev("=2^-1"), 0.5)
        self.assertEqual(self.ev("=-2^3^2"), -512.0)
        self.assertEqual(self.ev("=3*-2^2"), -12.0)
        self.assertEqual(self.ev("=--2^2"), 4.0)
        self.assertEqual(self.ev("=2^-1^2"), 0.5)
        self.assertEqual(self.ev("=4^3^2"), 262144.0)


class Issue3TopologicalRecalcTests(unittest.TestCase):
    def test_diamond_dependency(self):
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

    def test_deep_dag_and_mixed_cycle(self):
        s = Sheet()
        s.set("Z10", 2)
        s.set("M5", "=Z10+3")
        s.set("A1", "=M5+B2")
        s.set("B2", "=Z10*4")
        self.assertEqual(s.get("A1"), 13.0)
        s.set("Z10", 5)
        self.assertEqual(s.get("A1"), 28.0)

        # Cycle downstream of DAG and DAG downstream of cycle
        s.set("C1", "=C1+Z10")
        s.set("D1", "=C1+A1")
        self.assertEqual(s.get("C1"), ErrorValue("#CYCLE!"))
        self.assertEqual(s.get("D1"), ErrorValue("#CYCLE!"))
        s.set("Z10", 1)
        self.assertEqual(s.get("A1"), 8.0)
        self.assertEqual(s.get("C1"), ErrorValue("#CYCLE!"))
        self.assertEqual(s.get("D1"), ErrorValue("#CYCLE!"))


class Issue4CycleCleanupTests(unittest.TestCase):
    def test_overwrite_formula_removes_old_deps(self):
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

    def test_clear_cycle_cell(self):
        s = Sheet()
        s.set("A1", "=B1")
        s.set("B1", "=A1")
        s.set("A1", "")
        self.assertIsNone(s.get("A1"))
        self.assertIsNone(s.get("B1"))

    def test_syntax_error_does_not_corrupt_deps(self):
        s = Sheet()
        s.set("A1", "=B1+1")
        s.set("B1", 2)
        with self.assertRaises(FormulaSyntaxError):
            s.set("A1", "=1+")
        s.set("B1", 10)
        self.assertEqual(s.get("A1"), 11.0)


class Issue5AggregateRangeTests(unittest.TestCase):
    def test_sum_average_min_max_ignore_text_and_bool_in_ranges(self):
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

    def test_range_with_only_text_and_bool(self):
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

    def test_direct_args_still_coerced_and_errors_propagate(self):
        s = Sheet()
        s.set("A1", "hello")
        s.set("A2", True)
        s.set("B1", "=SUM(A2, 2)")
        s.set("B2", "=SUM(A1, 2)")
        self.assertEqual(s.get("B1"), 3.0)
        self.assertEqual(s.get("B2"), ErrorValue("#VALUE!"))

        s.set("C1", "=1/0")
        s.set("C2", 5)
        s.set("D1", "=SUM(C1:C2)")
        self.assertEqual(s.get("D1"), ErrorValue("#DIV/0!"))


class Issue6CopyCellTests(unittest.TestCase):
    def test_copy_literal_and_empty(self):
        s = Sheet()
        s.set("A1", 42)
        s.set("B1", "=A1*2")
        s.copy_cell("A1", "C1")
        self.assertEqual(s.get("C1"), 42.0)
        self.assertEqual(s.get_content("C1"), 42.0)

        s.copy_cell("Z9", "B1")
        self.assertIsNone(s.get("B1"))
        self.assertIsNone(s.get_content("B1"))

    def test_copy_formula_shifting_and_preservation(self):
        s = Sheet()
        s.set("A1", 10)
        s.set("B2", 20)
        s.set("B1", "=$A$1+A1")
        s.copy_cell("B1", "C3")
        self.assertEqual(s.get_formula("C3"), "=$A$1+B3")

        s.set("C1", '=sum( a1 : $b2 ) & "A1" & $a$1')
        s.copy_cell("C1", "D2")
        self.assertEqual(s.get_formula("D2"), '=sum( B2 : $B3 ) & "A1" & $A$1')

        s.set("D1", "=a$1+$a1")
        s.copy_cell("D1", "E3")
        self.assertEqual(s.get_formula("E3"), "=B$1+$A3")

    def test_copy_out_of_bounds_ref_error(self):
        s = Sheet()
        s.set("B2", "=A1+1")
        s.copy_cell("B2", "A1")
        self.assertEqual(s.get_formula("A1"), "=#REF!+1")
        self.assertEqual(s.get("A1"), ErrorValue("#REF!"))

        s.set("C3", "=SUM( A1:B2 )")
        s.copy_cell("C3", "B3")
        self.assertEqual(s.get_formula("B3"), "=SUM( #REF! )")
        self.assertEqual(s.get("B3"), ErrorValue("#REF!"))

    def test_copy_triggers_recalculation(self):
        s = Sheet()
        s.set("A1", 1)
        s.set("A2", 2)
        s.set("B1", "=A1*10")
        s.set("C2", "=B2+5")
        s.copy_cell("B1", "B2")
        self.assertEqual(s.get_formula("B2"), "=A2*10")
        self.assertEqual(s.get("B2"), 20.0)
        self.assertEqual(s.get("C2"), 25.0)


if __name__ == "__main__":
    unittest.main()
