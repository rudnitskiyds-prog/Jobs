import unittest

from scraper import classify, extract
from scraper.common import parse_conditions, parse_salary


class SalaryTest(unittest.TestCase):
    def test_range(self):
        s, lo, hi = parse_salary("Зарплата: от 60 000 до 80 000 ₽ на руки")
        self.assertEqual((lo, hi), (60000, 80000))
        self.assertIn("60 000", s)

    def test_k_suffix(self):
        _, lo, hi = parse_salary("ЗП 70-90к руб")
        self.assertEqual((lo, hi), (70000, 90000))

    def test_from(self):
        s, lo, _ = parse_salary("стажер-инженер данных в ПСБ (60 000 ₽)")
        self.assertEqual(lo, 60000)

    def test_words(self):
        s, lo, hi = parse_salary("З/П по результатам собеседования")
        self.assertIsNone(lo)
        self.assertTrue(s.lower().startswith("по результатам"))

    def test_prize_is_not_salary(self):
        _, lo, hi = parse_salary("Призовой фонд 1 600 000 ₽")
        self.assertIsNone(lo)


class ClassifyTest(unittest.TestCase):
    def test_employer_word_boundaries(self):
        self.assertEqual(classify.find_employer("Стажер в ВТБ, Москва")[0], "ВТБ")
        self.assertIsNone(classify.find_employer("отпуск и работа")[0])  # не «ОТП Банк»
        self.assertEqual(classify.find_employer("стажировка в Банке России")[0], "Банк России")

    def test_location(self):
        self.assertTrue(classify.location_ok("Стажер, Москва, гибрид"))
        self.assertFalse(classify.location_ok("Экономист, Саранск"))
        self.assertTrue(classify.location_ok("Стажер-аналитик в банк"))

    def test_conditions(self):
        c = parse_conditions("Гибридный формат, частичная занятость от 20 часов, официальное трудоустройство")
        self.assertIn("Гибрид", c)
        self.assertIn("Частичная занятость", c)
        self.assertIn("Официальное оформление", c)


class ProfileTest(unittest.TestCase):
    def test_accounting_excluded(self):
        for t in ("Бухгалтер", "Младший бухгалтер по МСФО", "Помощник бухгалтера", "Бухгалтер-стажер"):
            self.assertTrue(classify.is_excluded_title(t, "ВТБ"), t)

    def test_data_analysts_only_in_banks(self):
        self.assertFalse(classify.is_excluded_title("Стажер-Data Analyst", "Сбер"))
        self.assertFalse(classify.is_excluded_title("Стажёр аналитик данных", "Московская биржа"))
        self.assertTrue(classify.is_excluded_title("Стажёр дата-аналитик", "X5"))
        self.assertTrue(classify.is_excluded_title("Стажер Data Analytics", "Procter & Gamble"))
        self.assertTrue(classify.is_excluded_title("Стажер аналитик данных", None))

    def test_finance_roles_kept(self):
        for t in ("Стажер аудита финансовых учреждений", "Аналитик по финансовой отчетности", "Экономист"):
            self.assertFalse(classify.is_excluded_title(t, None), t)


class ExtractTest(unittest.TestCase):
    POST = ("Стажер в отдел M&A / Альфа-Банк\n\nОбязанности: финансовое моделирование, оценка компаний.\n"
            "Требования: студент 3-4 курса, Excel.\nУсловия: гибрид, 30 часов в неделю, 70 000 ₽. Москва.\n"
            "Откликнуться: https://example.com")

    def test_build_vacancy(self):
        v = extract.build(self.POST, url="https://t.me/x/1", source="t", source_type="telegram",
                          published=None, default_employer=None)
        self.assertIsNotNone(v)
        self.assertEqual(v.title, "Стажер в отдел M&A")
        self.assertEqual(v.employer, "Альфа-Банк")
        self.assertEqual(v.salary_from, 70000)
        self.assertEqual(v.sector, "Банки")
        self.assertEqual(v.kind, "Стажировка")
        self.assertIn("Гибрид", v.conditions)

    def test_event_rejected(self):
        text = "День открытых дверей в Сбере для студентов! Регистрация по ссылке, Москва"
        self.assertIsNone(extract.build(text, url="u", source="t", source_type="telegram",
                                        published=None, default_employer=None))

    def test_senior_rejected(self):
        text = "Ведущий аналитик в банк. Опыт от 3 лет. Зарплата 200 000 ₽. Москва. Откликнуться"
        self.assertIsNone(extract.build(text, url="u", source="t", source_type="telegram",
                                        published=None, default_employer=None))

    def test_it_rejected(self):
        text = "Стажер Java-разработчик в ВТБ. Требования: студент. Откликнуться. Москва"
        self.assertIsNone(extract.build(text, url="u", source="t", source_type="telegram",
                                        published=None, default_employer=None))


if __name__ == "__main__":
    unittest.main()
