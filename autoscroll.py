"""Прокрутка нажатием колеса мыши - как в браузере.

Нажали колесо над таблицей - на этом месте появляется значок ⇕. Мышь выше значка - список едет вверх,
ниже - вниз; чем дальше от значка, тем быстрее. Рядом со значком (DEAD_ZONE) - стоит.
У холста (график «Расписание»), который шире окна, - и влево-вправо (значок ✥).
- Нажали и отпустили колесо, не двигая мышь, - прокрутка остаётся включённой; выключает её любой щелчок
  (он больше ничего не делает - не выделяет строку, не красит клетку), колесо, Esc или переход на другую вкладку.
- Нажали, повели и отпустили (или держали дольше HOLD_MS) - прокрутка выключается, как только колесо отпущено.
Если всё и так помещается (прокручивать нечего) - ничего не происходит.

enable_autoscroll(root) - для всех таблиц (Treeview) и списков (Listbox) программы, в том числе в окнах,
открытых потом. Для других виджетов (холст) - MiddleClickAutoscroll(widget).
"""
import time
import tkinter as tk
import weakref

AUTOSCROLL_CLASSES = ("Treeview", "Listbox")


class MiddleClickAutoscroll:
    DEAD_ZONE = 10        # px от значка, где список стоит
    SPEED = 0.15          # строк в секунду на каждый пиксель за DEAD_ZONE
    MAX_RATE = 80.0       # строк в секунду, не быстрее
    PX_PER_ROW = 24       # холст прокручивается пикселями: одна «строка» - столько пикселей
    TICK_MS = 30
    HOLD_MS = 350         # держали колесо дольше - прокрутка только пока держат
    MARKER_SIZE = 30
    _TRANSPARENT = "#ff00fe"

    _instances = weakref.WeakKeyDictionary()

    @classmethod
    def for_widget(cls, widget):
        """Прокрутка этого виджета (создаётся при первом нажатии колеса)"""
        auto = cls._instances.get(widget)
        if auto is None:
            auto = cls(widget)
        return auto

    def __init__(self, widget):
        self.widget = widget
        self.active = False
        self.anchor = None          # (x_root, y_root) - где нажали колесо
        self.marker = None
        self._job = None
        self._carry = [0.0, 0.0]    # накопленная дробная часть (x, y)
        self._last = None
        self._pressed_at = 0.0
        self._moved = False
        self._old_cursor = ""
        self._prev_grab = None
        self._both_axes = False
        self.last_step_ms = 0.0     # сколько занял последний шаг с перерисовкой
        MiddleClickAutoscroll._instances[widget] = self
        self.attach(widget)
        top = widget.winfo_toplevel()
        for sequence in ("<ButtonPress-1>", "<ButtonPress-3>", "<MouseWheel>", "<Escape>"):
            top.bind(sequence, self._stop_event, add="+")

    def attach(self, widget):
        """Нажатие колеса над этим виджетом (например, надписью поверх таблицы) - как над самой таблицей"""
        widget.bind("<ButtonPress-2>", self.on_press, add="+")
        widget.bind("<ButtonRelease-2>", self.on_release, add="+")

    # ----- нажатие / отпускание колеса -----

    def on_press(self, event):
        if self.active:
            self.stop()
            return "break"
        self.start(event.x_root, event.y_root)
        return "break"

    def on_release(self, event=None):
        if not self.active:
            return "break"
        held_ms = (time.monotonic() - self._pressed_at) * 1000
        if self._moved or held_ms > self.HOLD_MS:
            self.stop()
        return "break"

    def _stop_event(self, event=None):
        if self.active:
            self.stop()
            return "break"

    # ----- что можно прокручивать -----

    def _is_canvas(self):
        return isinstance(self.widget, tk.Canvas)

    def _overflows(self, axis):
        try:
            first, last = getattr(self.widget, axis + "view")()
        except (tk.TclError, AttributeError):
            return False
        return first > 0.0 or last < 1.0

    def can_scroll_x(self):
        return self._is_canvas() and self._overflows("x")

    def can_scroll(self):
        return self._overflows("y") or self.can_scroll_x()

    # ----- включить / выключить -----

    def start(self, x_root, y_root):
        """Включить прокрутку со значком в точке (x_root, y_root). False - прокручивать нечего"""
        if self.active or not self.can_scroll():
            return False
        self.active = True
        self.anchor = (x_root, y_root)
        self._carry = [0.0, 0.0]
        self._last = time.monotonic()
        self._pressed_at = self._last
        self._moved = False
        self._both_axes = self.can_scroll_x()
        try:
            self._old_cursor = self.widget.cget("cursor")
        except tk.TclError:
            self._old_cursor = ""
        self._set_cursor(0, 0)
        self._show_marker()
        self._job = self.widget.after(self.TICK_MS, self._loop)
        return True

    def stop(self):
        if not self.active:
            return
        self.active = False
        if self._job is not None:
            try:
                self.widget.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None
        if self.marker is not None:
            try:
                self.marker.grab_release()
                self.marker.destroy()
            except tk.TclError:
                pass
            self.marker = None
        # Был открыт модальный диалог - возвращаем ему захват мыши
        prev, self._prev_grab = self._prev_grab, None
        if prev is not None:
            try:
                if prev.winfo_exists():
                    prev.grab_set()
            except tk.TclError:
                pass
        try:
            self.widget.configure(cursor=self._old_cursor)
        except tk.TclError:
            pass

    # ----- прокрутка -----

    def pointer(self):
        return self.widget.winfo_pointerxy()

    def still_shown(self):
        """Таблица на экране и окно программы активно"""
        try:
            return bool(self.widget.winfo_viewable()) and self.widget.focus_displayof() is not None
        except (tk.TclError, KeyError):
            return False

    def _loop(self):
        self._job = None
        if not self.active:
            return
        if not self.still_shown():   # ушли на другую вкладку или в другое окно
            self.stop()
            return
        started = time.monotonic()
        self.tick()
        try:
            self.widget.update_idletasks()   # перерисовать таблицу сейчас, чтобы знать, сколько это стоит
        except tk.TclError:
            pass
        self.last_step_ms = (time.monotonic() - started) * 1000
        if self.active:
            # Следующий шаг - не раньше, чем через время перерисовки + запас: иначе длинная таблица не успевает
            # перерисоваться, шаги идут без перерыва и программа перестаёт отвечать на мышь и клавиатуру
            delay = max(self.TICK_MS, int(self.last_step_ms) + self.TICK_MS)
            self._job = self.widget.after(delay, self._loop)

    def rate(self, offset):
        """Строк в секунду (со знаком) при смещении мыши offset пикселей от значка"""
        distance = abs(offset) - self.DEAD_ZONE
        if distance <= 0:
            return 0.0
        speed = min(self.MAX_RATE, distance * self.SPEED)
        return speed if offset > 0 else -speed

    def tick(self, dt=None):
        """Один шаг: прокрутить на столько, сколько набежало за dt секунд"""
        now = time.monotonic()
        if dt is None:
            dt = now - (self._last or now)
        self._last = now
        px, py = self.pointer()
        rate_x = self.rate(px - self.anchor[0]) if self._both_axes else 0.0
        rate_y = self.rate(py - self.anchor[1])
        self._set_cursor(rate_x, rate_y)
        if rate_x or rate_y:
            self._moved = True
        for index, (axis, rate) in enumerate((("x", rate_x), ("y", rate_y))):
            if rate == 0:
                self._carry[index] = 0.0
                continue
            per_second = rate * self.PX_PER_ROW if self._is_canvas() else rate
            self._carry[index] += per_second * dt
            step = int(self._carry[index])
            if step:
                self._carry[index] -= step
                self._scroll(axis, step)

    def _scroll(self, axis, step):
        """Таблица/список - на step строк; холст - на step пикселей"""
        if not self._is_canvas():
            getattr(self.widget, axis + "view_scroll")(step, "units")
            return
        first, last = getattr(self.widget, axis + "view")()
        size = self.widget.winfo_width() if axis == "x" else self.widget.winfo_height()
        if last <= first or size <= 1:
            return
        total = size / (last - first)
        getattr(self.widget, axis + "view_moveto")(max(0.0, first + step / total))

    # ----- значок и курсор -----

    def _set_cursor(self, rate_x, rate_y):
        if rate_x == 0 and rate_y == 0:
            cursor = "fleur" if self._both_axes else "sb_v_double_arrow"
        elif abs(rate_x) > abs(rate_y):
            cursor = "sb_right_arrow" if rate_x > 0 else "sb_left_arrow"
        else:
            cursor = "sb_down_arrow" if rate_y > 0 else "sb_up_arrow"
        try:
            self.widget.configure(cursor=cursor)
        except tk.TclError:
            pass

    def _show_marker(self):
        size = self.MARKER_SIZE
        marker = tk.Toplevel(self.widget)
        marker.overrideredirect(True)
        try:
            marker.attributes("-topmost", True)
            marker.attributes("-transparentcolor", self._TRANSPARENT)
            background = self._TRANSPARENT
        except tk.TclError:
            background = "white"
        canvas = tk.Canvas(marker, width=size, height=size, bg=background, highlightthickness=0, bd=0)
        canvas.pack()
        canvas.create_oval(1, 1, size - 2, size - 2, fill="white", outline="#90a4ae", width=1.5)
        mid, color = size / 2, "#455a64"
        canvas.create_polygon(mid, 5, mid - 5, 11, mid + 5, 11, fill=color, outline="")
        canvas.create_polygon(mid, size - 6, mid - 5, size - 12, mid + 5, size - 12, fill=color, outline="")
        if self._both_axes:
            canvas.create_polygon(5, mid, 11, mid - 5, 11, mid + 5, fill=color, outline="")
            canvas.create_polygon(size - 6, mid, size - 12, mid - 5, size - 12, mid + 5, fill=color, outline="")
        canvas.create_oval(mid - 2, mid - 2, mid + 2, mid + 2, fill=color, outline="")
        x, y = self.anchor
        marker.geometry(f"{size}x{size}+{int(x - size / 2)}+{int(y - size / 2)}")
        # Пока прокрутка включена, все щелчки мыши приходят сюда: щелчок только выключает прокрутку
        # и не попадает в таблицу (не выделяет строку, не красит клетку графика)
        marker.bind("<ButtonPress-2>", self.on_press)
        marker.bind("<ButtonRelease-2>", self.on_release)
        for sequence in ("<ButtonPress-1>", "<ButtonPress-3>", "<MouseWheel>", "<Escape>"):
            marker.bind(sequence, self._stop_event)
        self.marker = marker
        try:
            self._prev_grab = marker.grab_current()
            marker.update_idletasks()
            if marker.winfo_viewable():
                marker.grab_set()
        except tk.TclError:
            pass   # без захвата: щелчок выключит прокрутку через привязки окна


def enable_autoscroll(root):
    """Прокрутка колесом - во всех таблицах и списках программы (и в окнах, открытых потом)"""
    def press(event):
        return MiddleClickAutoscroll.for_widget(event.widget).on_press(event)

    def release(event):
        auto = MiddleClickAutoscroll._instances.get(event.widget)
        return auto.on_release(event) if auto else None

    for class_name in AUTOSCROLL_CLASSES:
        root.bind_class(class_name, "<ButtonPress-2>", press, add="+")
        root.bind_class(class_name, "<ButtonRelease-2>", release, add="+")
    # Esc выключает прокрутку, где бы ни был фокус клавиатуры (в поле поиска, в другом окне программы)
    root.bind_all("<Escape>", lambda event: stop_all(), add="+")


def stop_all():
    """Выключить все включённые прокрутки"""
    for auto in list(MiddleClickAutoscroll._instances.values()):
        if auto.active:
            auto.stop()
