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


if __name__ == "__main__":
    unittest.main()
