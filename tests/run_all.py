# -*- coding: utf-8 -*-
"""Запуск всех автотестов на ТЕСТОВОЙ базе:  python tests/run_all.py
Только часть:  python tests/run_all.py hint edit   (тесты, в имени которых есть hint или edit)
Только на компьютере разработчика: нужен ALEXAN_TEST_DB=1 в config/.env (иначе тесты откажутся запускаться).
Подробный лог - tests/last_run.txt, коротко - в консоли. Код выхода 0 - всё прошло, 1 - есть провалы."""
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Harness  # noqa: E402
import test_positive  # noqa: E402
import test_negative  # noqa: E402

# Новые наборы проверок - добавлять сюда
SUITES = [("Позитивные", test_positive), ("Негативные", test_negative)]
FILTERS = sys.argv[1:]
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_run.txt")


def main():
    try:
        h = Harness(LOG_PATH)
    except SystemExit as e:
        print(e)
        return 2
    status = [1]

    def run():
        try:
            for title, suite in SUITES:
                h.group = title
                h.log(f"\n==== {title} ({suite.__name__}) ====")
                try:
                    suite.prepare(h)
                except Exception as e:
                    h.check(f"{title}: подготовка", False, str(e))
                    continue
                for test in suite.TESTS:
                    if FILTERS and not any(f in test.__name__ for f in FILTERS):
                        continue
                    h.group = f"{title} / {test.__name__}"
                    h.log(f"\n{test.__name__}: {(test.__doc__ or '').strip().splitlines()[0]}")
                    try:
                        test(h)
                    except Exception:
                        h.check(f"{test.__name__} без исключений", False, traceback.format_exc()[-1500:])
        finally:
            try:
                h.cleanup()
            except Exception:
                h.check("уборка без исключений", False, traceback.format_exc()[-800:])
            total, failed = h.summary()
            print(f"Проверок: {total}, прошли: {total - len(failed)}, провалы: {len(failed)}")
            for group, name in failed:
                print(f"  FAIL [{group}] {name}")
            print(f"Подробности: {LOG_PATH}")
            sys.stdout.flush()
            status[0] = 1 if failed else 0
            os._exit(status[0])

    h.root.after(1500, run)
    h.root.mainloop()
    return status[0]


if __name__ == "__main__":
    sys.exit(main())
