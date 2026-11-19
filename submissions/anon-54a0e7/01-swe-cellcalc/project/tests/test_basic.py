import unittest

from cellcalc import ErrorValue, FormulaSyntaxError, Sheet


class LiteralTests(unittest.TestCase):
    def test_numbers_and_text(self):
        s = Sheet()
        s.set("A1", 3)
        s.set("A2", "4.5")
        s.set("A3", "hello")
        s.set("A4", True)
        self.assertEqual(s.get("A1"), 3.0)
        self.assertEqual(s.get("A2"), 4.5)
        self.assertEqual(s.get("A3"), "hello")
        self.assertIs(s.get("A4"), True)
        self.assertIsNone(s.get("B9"))

    def test_clear(self):
        s = Sheet()
        s.set("A1", 3)
        s.set("A1", None)
        self.assertIsNone(s.get("A1"))
        self.assertIsNone(s.get_content("A1"))


class ArithmeticTests(unittest.TestCase):
    def ev(self, formula):
        s = Sheet()
        s.set("A1", formula)
        return s.get("A1")

    def test_precedence_basic(self):
        self.assertEqual(self.ev("=1+2*3"), 7.0)
        self.assertEqual(self.ev("=(1+2)*3"), 9.0)
        self.assertEqual(self.ev("=10-4-3"), 3.0)
        self.assertEqual(self.ev("=2^10"), 1024.0)
        self.assertEqual(self.ev("=-3*2"), -6.0)

    def test_div_zero(self):
        self.assertEqual(self.ev("=1/0"), ErrorValue("#DIV/0!"))

    def test_concat_and_compare(self):
        self.assertEqual(self.ev('="a"&1&TRUE'), "a1TRUE")
        self.assertIs(self.ev("=2>1"), True)
        self.assertIs(self.ev('="abc"="ABC"'), True)

    def test_unknown_name(self):
        self.assertEqual(self.ev("=FOO(1)"), ErrorValue("#NAME?"))
        self.assertEqual(self.ev("=foo+1"), ErrorValue("#NAME?"))

    def test_syntax_error_leaves_sheet_unchanged(self):
        s = Sheet()
        s.set("A1", 5)
        with self.assertRaises(FormulaSyntaxError):
            s.set("A1", "=1+")
        self.assertEqual(s.get("A1"), 5.0)


class ReferenceTests(unittest.TestCase):
    def test_chain(self):
        s = Sheet()
        s.set("A1", 2)
        s.set("B1", "=A1*10")
        s.set("C1", "=B1+1")
        self.assertEqual(s.get("C1"), 21.0)
        s.set("A1", 3)
        self.assertEqual(s.get("B1"), 30.0)
        self.assertEqual(s.get("C1"), 31.0)

    def test_empty_reference_is_zero(self):
        s = Sheet()
        s.set("A1", "=B7+1")
        self.assertEqual(s.get("A1"), 1.0)

    def test_functions(self):
        s = Sheet()
        for i, v in enumerate([4, 8, 15, 16, 23, 42], start=1):
            s.set(f"B{i}", v)
        s.set("C1", "=SUM(B1:B6)")
        s.set("C2", "=AVERAGE(B1:B6)")
        s.set("C3", "=MAX(B1:B6)-MIN(B1:B6)")
        s.set("C4", "=COUNT(B1:B10)")
        s.set("C5", '=IF(C1>100, "big", "small")')
        s.set("C6", "=ROUND(C2/7, 2)")
        self.assertEqual(s.get("C1"), 108.0)
        self.assertEqual(s.get("C2"), 18.0)
        self.assertEqual(s.get("C3"), 38.0)
        self.assertEqual(s.get("C4"), 6.0)
        self.assertEqual(s.get("C5"), "big")
        self.assertEqual(s.get("C6"), 2.57)

    def test_error_propagation(self):
        s = Sheet()
        s.set("A1", "=1/0")
        s.set("A2", "=A1+1")
        s.set("A3", "=SUM(A1:A2)")
        self.assertEqual(s.get("A2"), ErrorValue("#DIV/0!"))
        self.assertEqual(s.get("A3"), ErrorValue("#DIV/0!"))

    def test_self_cycle(self):
        s = Sheet()
        s.set("A1", "=A1+1")
        self.assertEqual(s.get("A1"), ErrorValue("#CYCLE!"))

    def test_two_cell_cycle_and_downstream(self):
        s = Sheet()
        s.set("A1", "=B1+1")
        s.set("B1", "=A1+1")
        s.set("C1", "=A1*2")
        self.assertEqual(s.get("A1"), ErrorValue("#CYCLE!"))
        self.assertEqual(s.get("B1"), ErrorValue("#CYCLE!"))
        self.assertEqual(s.get("C1"), ErrorValue("#CYCLE!"))

    def test_get_formula(self):
        s = Sheet()
        s.set("A1", "=SUM(B1:B3) * 2")
        self.assertEqual(s.get_formula("A1"), "=SUM(B1:B3) * 2")
        self.assertEqual(s.get_content("A1"), "=SUM(B1:B3) * 2")
        self.assertIsNone(s.get_formula("A2"))


class IssueRegressionTests(unittest.TestCase):
    def test_issue1_columns_after_z(self):
        from cellcalc.refs import col_to_index, index_to_col

        self.assertEqual(col_to_index("A"), 1)
        self.assertEqual(col_to_index("Z"), 26)
        self.assertEqual(col_to_index("AA"), 27)
        self.assertEqual(col_to_index("AZ"), 52)
        self.assertEqual(col_to_index("BA"), 53)
        self.assertEqual(col_to_index("ZZ"), 702)
        self.assertEqual(col_to_index("AAA"), 703)
        self.assertEqual(col_to_index("ZZZ"), 18278)
        for idx in (1, 26, 27, 52, 53, 702, 703, 18278):
            col = index_to_col(idx)
            self.assertEqual(col_to_index(col), idx)

        s = Sheet()
        s.set("A1", 1)
        s.set("AA1", 100)
        self.assertEqual(s.get("A1"), 1.0)
        self.assertEqual(s.get("AA1"), 100.0)
        s.set("ZZZ5", "=AA1+Z1")
        s.set("Z1", 23)
        self.assertEqual(s.get("ZZZ5"), 123.0)

    def test_issue2_power_precedence_and_associativity(self):
        s = Sheet()
        s.set("A1", "=-2^2")
        s.set("A2", "=2^3^2")
        s.set("A3", "=2^-1")
        s.set("A4", "=2^-2^2")
        s.set("A5", "=(-2)^2")
        self.assertEqual(s.get("A1"), -4.0)
        self.assertEqual(s.get("A2"), 512.0)
        self.assertEqual(s.get("A3"), 0.5)
        self.assertEqual(s.get("A4"), 0.0625)
        self.assertEqual(s.get("A5"), 4.0)

    def test_issue3_topological_recalculation(self):
        s = Sheet()
        s.set("A1", 1)
        s.set("B2", "=A1*2")
        s.set("C5", "=B2+1")
        s.set("A3", "=B2+C5")
        self.assertEqual(s.get("A3"), 5.0)
        s.set("A1", 10)
        self.assertEqual(s.get("A3"), 41.0)

    def test_issue4_cycle_cleanup(self):
        s = Sheet()
        s.set("A1", "=B1")
        s.set("A1", 1)
        s.set("B1", "=A1")
        self.assertEqual(s.get("B1"), 1.0)

        # Breaking a real cycle
        s2 = Sheet()
        s2.set("A1", "=B1+1")
        s2.set("B1", "=A1+1")
        s2.set("C1", "=B1*2")
        self.assertEqual(s2.get("A1"), ErrorValue("#CYCLE!"))
        self.assertEqual(s2.get("C1"), ErrorValue("#CYCLE!"))
        s2.set("A1", 5)
        self.assertEqual(s2.get("A1"), 5.0)
        self.assertEqual(s2.get("B1"), 6.0)
        self.assertEqual(s2.get("C1"), 12.0)

    def test_issue5_aggregates_ignore_text_and_bool_in_ranges(self):
        s = Sheet()
        s.set("B1", 1)
        s.set("B2", "n/a")
        s.set("B3", 2)
        s.set("B4", True)
        s.set("C1", "=SUM(B1:B4)")
        s.set("C2", "=AVERAGE(B1:B4)")
        s.set("C3", "=MIN(B1:B4)")
        s.set("C4", "=MAX(B1:B4)")
        s.set("C5", "=SUM(B1:B4, TRUE)")
        s.set("C6", '=SUM(B1:B4, "n/a")')
        self.assertEqual(s.get("C1"), 3.0)
        self.assertEqual(s.get("C2"), 1.5)
        self.assertEqual(s.get("C3"), 1.0)
        self.assertEqual(s.get("C4"), 2.0)
        self.assertEqual(s.get("C5"), 4.0)
        self.assertEqual(s.get("C6"), ErrorValue("#VALUE!"))

    def test_issue6_copy_cell(self):
        s = Sheet()
        s.set("A1", 10)
        s.set("B1", "=$A$1+A1")
        s.copy_cell("B1", "C3")
        self.assertEqual(s.get_formula("C3"), "=$A$1+B3")
        s.set("B3", 5)
        self.assertEqual(s.get("C3"), 15.0)

        s.set("B2", "=A1+1")
        s.copy_cell("B2", "A1")
        self.assertEqual(s.get_formula("A1"), "=#REF!+1")
        self.assertEqual(s.get("A1"), ErrorValue("#REF!"))

        # Mixed refs, ranges, casing, whitespace, string literals
        s2 = Sheet()
        s2.set("C3", '=sum( a1:B$2, $C1 ) & " A1:B2 "')
        s2.copy_cell("C3", "D5")
        self.assertEqual(s2.get_formula("D5"), '=sum( B3:C$2, $C3 ) & " A1:B2 "')

        # Range shifting out of bounds collapses whole range to single #REF!
        s2.copy_cell("C3", "B2")
        self.assertEqual(s2.get_formula("B2"), '=sum( #REF!, #REF! ) & " A1:B2 "')

        # Literal and empty copy
        s2.set("E1", "hello")
        s2.copy_cell("E1", "E2")
        self.assertEqual(s2.get("E2"), "hello")
        s2.copy_cell("Z9", "E2")
        self.assertIsNone(s2.get("E2"))


if __name__ == "__main__":
    unittest.main()
