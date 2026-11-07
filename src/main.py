"""SMS TEST v3.1: simple Android Flet UI for authorized SMS API testing."""
from __future__ import annotations

import asyncio
from uuid import uuid4

import flet as ft
import requests

from storage import decode_records, encode_records

from engine import (
    DELAY_SECONDS,
    MAX_HISTORY,
    MAX_PROFILES,
    MAX_REQUESTS,
    auth_like,
    history_item,
    poll_delivery,
    safe_url_label,
    send_one,
    url_overview,
    validate_phone,
    validate_url,
)

BG = "#0B1322"
SURFACE = "#152238"
BLUE = "#58CEE8"
WHITE = "#E6F1FD"
MUTED = "#A5B8CC"
GOOD = "#74E8AE"
WARN = "#F4D18A"
BAD = "#FF8D94"


def card(*controls):
    return ft.Container(
        bgcolor=SURFACE,
        padding=15,
        border_radius=15,
        content=ft.Column(controls=list(controls), spacing=10),
    )


async def main(page: ft.Page):
    page.title = "SMS TEST v3.1"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = BG
    page.padding = 12
    page.theme = ft.Theme(color_scheme_seed=BLUE)

    # The app keeps references to services for its whole lifetime.
    prefs = ft.SharedPreferences()
    PROFILES_KEY = "smstest.v3.profiles"
    HISTORY_KEY = "smstest.v3.history"
    SELECTED_KEY = "smstest.v3.selected_id"
    WITHOUT_PLUS_KEY = "smstest.v3.phone_without_plus"
    storage_warning = ""
    try:
        profiles = decode_records(await prefs.get(PROFILES_KEY), MAX_PROFILES)
        history = decode_records(await prefs.get(HISTORY_KEY), MAX_HISTORY)
        saved_selected_id = await prefs.get(SELECTED_KEY)
        saved_without_plus = await prefs.get(WITHOUT_PLUS_KEY)
    except Exception as exc:
        profiles, history = [], []
        saved_selected_id, saved_without_plus = None, False
        storage_warning = f"Не удалось загрузить сохранённые ссылки: {type(exc).__name__}"
    profiles = [p for p in profiles if isinstance(p.get("id"), str) and isinstance(p.get("url"), str)]
    selected_id = (
        saved_selected_id
        if isinstance(saved_selected_id, str) and any(p["id"] == saved_selected_id for p in profiles)
        else (profiles[0]["id"] if profiles else None)
    )
    running = False
    stop_requested = False

    feedback = ft.Text("", size=13, color=MUTED)
    phone_entry = ft.TextField(
        label="Номер с кодом страны (можно без +)",
        hint_text="79991234567 или +79991234567",
        keyboard_type=ft.KeyboardType.PHONE,
        autocorrect=False,
    )
    phone_info = ft.Text("Введите номер, затем нажмите «Проверить».", size=12, color=MUTED)
    count_entry = ft.TextField(
        label=f"Количество запросов (1–{MAX_REQUESTS})",
        value="1",
        keyboard_type=ft.KeyboardType.NUMBER,
        width=250,
    )
    token_entry = ft.TextField(
        label="Bearer API-ключ (не сохраняется)",
        hint_text="Необязательно",
        password=True,
        can_reveal_password=True,
    )
    owned_checkbox = ft.Checkbox(
        label="Подтверждаю: это мой номер и мой API, тест разрешён",
        value=False,
    )
    without_plus_checkbox = ft.Checkbox(
        label="Передавать в поле phone только цифры (без +)",
        value=bool(saved_without_plus),
    )
    profile_display = ft.Text("", size=13, color=WHITE)
    progress = ft.ProgressBar(value=0, color=BLUE, bgcolor="#2A3E57", bar_height=9)
    progress_text = ft.Text("0 / 0", color=MUTED, size=12)
    result_text = ft.Text("Нет результатов", color=MUTED, size=12)
    log_view = ft.Column(spacing=5)
    new_name = ft.TextField(label="Название профиля", hint_text="Мой SMS API")
    new_url = ft.TextField(
        label="Полный HTTPS URL (можно длинный, со всеми параметрами)",
        hint_text="https://example.com/api/send?foo=bar&x=1",
        multiline=True,
        min_lines=2,
        max_lines=5,
        autocorrect=False,
    )
    new_status_url = ft.TextField(
        label="URL проверки доставки (необязательно)",
        hint_text="https://example.com/api/status",
        multiline=True,
        min_lines=1,
        max_lines=3,
        autocorrect=False,
    )
    url_preview = ft.Text("URL ещё не проверен", color=MUTED, size=12)

    main_column = ft.Column(spacing=14, scroll=ft.ScrollMode.AUTO, expand=True)

    def inform(message: str, color: str = MUTED):
        feedback.value = message
        feedback.color = color
        page.update()

    async def save_profiles() -> bool:
        try:
            # SharedPreferences does not support list[dict] directly.
            ok = await prefs.set(PROFILES_KEY, encode_records(profiles, MAX_PROFILES))
            if ok is False:
                raise OSError("SharedPreferences вернул False")
            return True
        except Exception as exc:
            inform(f"Не удалось сохранить ссылки: {exc}", BAD)
            return False

    async def save_selection() -> bool:
        try:
            ok = await prefs.set(SELECTED_KEY, selected_id or "")
            if ok is False:
                raise OSError("SharedPreferences вернул False")
            return True
        except Exception as exc:
            inform(f"Не удалось сохранить выбор: {exc}", WARN)
            return False

    async def save_history():
        try:
            await prefs.set(HISTORY_KEY, encode_records(history, MAX_HISTORY))
        except Exception as exc:
            inform(f"История не сохранена: {type(exc).__name__}", WARN)

    async def change_phone_format(e=None):
        try:
            await prefs.set(WITHOUT_PLUS_KEY, bool(without_plus_checkbox.value))
        except Exception:
            inform("Не удалось сохранить настройку номера", WARN)

    without_plus_checkbox.on_change = change_phone_format

    def current_profile():
        return next((p for p in profiles if p.get("id") == selected_id), None)

    def refresh_profile_display():
        p = current_profile()
        if p is None:
            profile_display.value = "Профиль не выбран — добавьте URL на вкладке «Ссылки»."
        else:
            kind = "Авторизация → браузер" if auth_like(p["url"]) else "Собственный API → POST"
            profile_display.value = f"{p['name']} · {safe_url_label(p['url'])}\nРежим: {kind}"

    def check_number(e=None):
        try:
            checked = validate_phone(phone_entry.value or "")
        except ValueError as exc:
            phone_info.value = str(exc)
            phone_info.color = BAD
        else:
            phone_info.value = (
                f"✓ {checked.number}  ·  {checked.country}  ·  код {checked.country_code}"
            )
            phone_info.color = GOOD
        page.update()

    def inspect_link(e=None):
        try:
            details = url_overview(new_url.value or "")
            if new_status_url.value and new_status_url.value.strip():
                validate_url(new_status_url.value)
            kind = (
                "Ссылка авторизации. Открывается в браузере, не POST."
                if details["kind"] == "browser"
                else "HTTPS URL API. POST допускается только для своего API."
            )
            url_preview.value = (
                f"Домен: {details['host']}\n"
                f"Путь: {details['path']}\n"
                f"Параметров URL: {details['params']}\n{kind}"
            )
            url_preview.color = GOOD if details["kind"] == "api" else WARN
        except ValueError as exc:
            url_preview.value = f"Ошибка: {exc}"
            url_preview.color = BAD
        page.update()

    async def add_profile(e=None):
        nonlocal selected_id
        if len(profiles) >= MAX_PROFILES:
            inform(f"Максимум {MAX_PROFILES} профилей", BAD)
            return
        try:
            new_profile_url = validate_url(new_url.value or "")
            status_url = (new_status_url.value or "").strip()
            if status_url:
                validate_url(status_url)
                if auth_like(status_url):
                    raise ValueError("URL проверки доставки не должен быть ссылкой входа")
        except ValueError as exc:
            inform(f"URL не добавлен: {exc}", BAD)
            return

        profile = {
            "id": uuid4().hex,
            "name": (new_name.value or "Новый URL").strip()[:60] or "Новый URL",
            "url": new_profile_url,
            "status_url": status_url,
        }
        old_selected_id = selected_id
        profiles.append(profile)
        selected_id = profile["id"]
        if not await save_profiles():
            profiles.pop()
            selected_id = old_selected_id
            return
        await save_selection()
        new_name.value = ""
        new_url.value = ""
        new_status_url.value = ""
        url_preview.value = "Ссылка сохранена. Длинные параметры URL сохранены целиком."
        url_preview.color = GOOD
        inform("Профиль добавлен и выбран", GOOD)
        render_links()

    async def pick_profile(e, profile_id: str):
        nonlocal selected_id
        selected_id = profile_id
        await save_selection()
        inform("Профиль выбран", GOOD)
        render_links()

    async def delete_profile(e, profile_id: str):
        nonlocal selected_id
        old_profiles = profiles[:]
        old_selected = selected_id
        profiles[:] = [p for p in profiles if p.get("id") != profile_id]
        if selected_id == profile_id:
            selected_id = profiles[0].get("id") if profiles else None
        if not await save_profiles():
            profiles[:] = old_profiles
            selected_id = old_selected
            return
        await save_selection()
        inform("Профиль удалён", WARN)
        render_links()

    def log(message: str, color: str = MUTED):
        log_view.controls.insert(0, ft.Text(message, color=color, size=12))
        del log_view.controls[10:]
        page.update()

    def ask_stop(e=None):
        nonlocal stop_requested
        stop_requested = True
        inform("Остановка после текущего запроса…", WARN)

    async def add_history_record(profile, status: str, delivery: str):
        history.insert(0, history_item(profile, status, delivery))
        del history[MAX_HISTORY:]
        await save_history()

    async def perform_send(profile, checked_number, token: str):
        return await asyncio.to_thread(
            send_one,
            profile["url"],
            checked_number,
            token,
            without_plus=bool(without_plus_checkbox.value),
        )

    async def check_delivery(profile, message_id, token):
        if not profile.get("status_url") or not message_id:
            return "unknown"
        # The provider's status API may initially return pending/queued.
        for attempt in range(3):
            try:
                delivery = await asyncio.to_thread(
                    poll_delivery, profile["status_url"], message_id, token
                )
            except (requests.RequestException, ValueError) as exc:
                return f"Ошибка статуса: {type(exc).__name__}"
            if delivery in {"delivered", "failed", "rejected"}:
                return delivery
            if attempt < 2:
                await asyncio.sleep(2)
        return delivery

    async def start_test(e=None):
        nonlocal running, stop_requested
        if running:
            return
        p = current_profile()
        if not p:
            inform("Сначала добавьте и выберите профиль API", BAD)
            return
        if auth_like(p["url"]):
            inform("Это ссылка входа/авторизации — откройте её в браузере на вкладке «Ссылки»", WARN)
            return
        if not owned_checkbox.value:
            inform("Нужно подтвердить право тестирования номера и API", WARN)
            return
        try:
            checked = validate_phone(phone_entry.value or "")
            count = int((count_entry.value or "").strip())
            if count < 1 or count > MAX_REQUESTS:
                raise ValueError(f"Введите количество от 1 до {MAX_REQUESTS}")
        except (ValueError, TypeError) as exc:
            inform(f"Ошибка ввода: {exc}", BAD)
            return

        running = True
        stop_requested = False
        progress.value = 0
        progress_text.value = f"0 / {count}"
        log_view.controls.clear()
        accepted = 0
        delivered = 0
        errors = 0
        tried = 0
        rate_limited = False
        token = token_entry.value or ""
        inform("Выполняются реальные POST-запросы к выбранному API…", BLUE)

        try:
            for i in range(count):
                if stop_requested:
                    break
                try:
                    outcome = await perform_send(p, checked.number, token)
                    tried += 1
                    http = outcome["status"]
                    status = f"HTTP {http}"
                    if outcome["accepted"]:
                        accepted += 1
                        log(f"{i+1}. {status} — API приняло запрос", GOOD)
                        delivery = await check_delivery(p, outcome["message_id"], token)
                        if delivery == "delivered":
                            delivered += 1
                            log(f"   Доставка: {delivery}", GOOD)
                        elif delivery != "unknown":
                            log(f"   Доставка: {delivery}", WARN)
                    else:
                        errors += 1
                        delivery = "unknown"
                        log(f"{i+1}. {status} — ошибка или отказ", BAD)
                    await add_history_record(p, status, delivery)
                    if http == 429:
                        rate_limited = True
                        inform("API вернул 429: отправка остановлена", WARN)
                except (requests.RequestException, ValueError) as exc:
                    errors += 1
                    tried += 1
                    # URLs may contain private query strings: never log them.
                    log(f"{i+1}. Сбой: {type(exc).__name__}", BAD)
                    await add_history_record(p, "Ошибка соединения", "unknown")

                progress.value = (i + 1) / count
                progress_text.value = f"{i + 1} / {count}"
                result_text.value = (
                    f"Попыток: {tried}  ·  HTTP 2xx: {accepted}  ·  "
                    f"Доставлено: {delivered}  ·  Ошибок: {errors}"
                )
                page.update()
                if rate_limited:
                    break
                if i + 1 < count and not stop_requested:
                    await asyncio.sleep(DELAY_SECONDS)
        finally:
            running = False
            if rate_limited:
                inform("API ответил 429: остановлено во избежание превышения лимита", WARN)
            elif not stop_requested:
                inform("Готово. HTTP 2xx не гарантирует доставку SMS.", GOOD)
            else:
                inform("Запуск остановлен пользователем", WARN)

    async def demo(e=None):
        nonlocal running
        if running:
            return
        running = True
        log_view.controls.clear()
        progress.value = 0
        progress_text.value = "0 / 3"
        try:
            inform("Демо: без сетевых запросов и SMS", BLUE)
            for i in range(3):
                await asyncio.sleep(.4)
                log(f"Демо {i+1}: пример HTTP 202 (НЕ реальный ответ)", BLUE)
                progress.value = (i + 1) / 3
                progress_text.value = f"{i+1} / 3"
                page.update()
            result_text.value = "Демо завершено — реальные запросы: 0"
        finally:
            running = False
            inform("Демо завершено", GOOD)

    def render_home(e=None):
        refresh_profile_display()
        main_column.controls = [
            ft.Text("Главная", size=23, weight=ft.FontWeight.BOLD, color=WHITE),
            card(
                ft.Text("01 · Номер телефона", color=BLUE, weight=ft.FontWeight.BOLD),
                phone_entry,
                ft.OutlinedButton("Проверить номер и страну", on_click=check_number),
                phone_info,
            ),
            card(
                ft.Text("02 · Выбранный URL", color=BLUE, weight=ft.FontWeight.BOLD),
                profile_display,
                ft.OutlinedButton("+ Добавить / выбрать URL", on_click=render_links),
            ),
            card(
                ft.Text("03 · Отправка (свой SMS API)", color=BLUE, weight=ft.FontWeight.BOLD),
                count_entry,
                without_plus_checkbox,
                token_entry,
                owned_checkbox,
                ft.Row([
                    ft.Button("Отправить POST", on_click=start_test),
                    ft.OutlinedButton("Стоп", on_click=ask_stop),
                ], wrap=True),
                ft.OutlinedButton("Демо без отправки", on_click=demo),
                progress,
                progress_text,
                result_text,
                ft.Text("Журнал этого запуска", color=MUTED, size=12),
                log_view,
            ),
        ]
        page.update()

    def render_links(e=None):
        refresh_profile_display()
        items = [
            ft.Text("Профили URL", size=23, weight=ft.FontWeight.BOLD, color=WHITE),
            card(
                ft.Text("+ Быстро добавить длинную ссылку", color=BLUE, weight=ft.FontWeight.BOLD),
                ft.Text(
                    "Вставь URL целиком с ?, &, = и %. "
                    "Сохранённые ссылки остаются после закрытия приложения. "
                    "Для страниц входа требуется браузер.",
                    color=MUTED, size=12,
                ),
                new_name,
                new_url,
                new_status_url,
                ft.Row([
                    ft.OutlinedButton("Распознать URL", on_click=inspect_link),
                    ft.Button("+ Сохранить URL", on_click=add_profile),
                ], wrap=True),
                url_preview,
            ),
        ]
        if not profiles:
            items.append(card(ft.Text("Пока нет сохранённых URL", color=MUTED)))
        for p in profiles:
            profile_id = p.get("id")
            is_auth = auth_like(p["url"])

            async def select_handler(e, pid=profile_id):
                await pick_profile(e, pid)

            async def delete_handler(e, pid=profile_id):
                await delete_profile(e, pid)

            active = "✓ Выбран" if selected_id == profile_id else "Выбрать"
            mode = "Вход через браузер" if is_auth else "POST для собственного API"
            items.append(card(
                ft.Text(p.get("name", "Профиль"), color=WHITE, weight=ft.FontWeight.BOLD),
                ft.Text(f"{safe_url_label(p['url'])}", color=MUTED, size=12),
                ft.Text(mode, color=WARN if is_auth else GOOD, size=12),
                ft.Row([
                    ft.OutlinedButton(active, on_click=select_handler),
                    ft.Button("Открыть ссылку", url=p["url"]),
                    ft.OutlinedButton("Удалить", on_click=delete_handler),
                ], wrap=True),
            ))
        main_column.controls = items
        page.update()

    async def clear_history(e=None):
        history.clear()
        await save_history()
        render_history()

    def render_history(e=None):
        items = [
            ft.Text("История", size=23, weight=ft.FontWeight.BOLD, color=WHITE),
            ft.Text("Хранятся статус и путь API, без номера и параметров URL.", color=MUTED, size=12),
            ft.OutlinedButton("Очистить историю", on_click=clear_history),
        ]
        if not history:
            items.append(card(ft.Text("История пуста", color=MUTED)))
        for h in history[:MAX_HISTORY]:
            items.append(card(
                ft.Text(f"{h.get('at','')}  ·  {h.get('profile','')}", color=WHITE),
                ft.Text(h.get("endpoint", ""), color=MUTED, size=12),
                ft.Text(
                    f"{h.get('status','')}  ·  Доставка: {h.get('delivery','unknown')}",
                    color=GOOD if h.get("delivery") == "delivered" else MUTED,
                    size=12,
                ),
            ))
        main_column.controls = items
        page.update()

    def render_about(e=None):
        main_column.controls = [
            ft.Text("О приложении", size=23, weight=ft.FontWeight.BOLD, color=WHITE),
            card(
                ft.Text("SMS TEST v3.1 · @zronu", color=BLUE, weight=ft.FontWeight.BOLD),
                ft.Text(
                    "Проверка международных номеров с + или без +; "
                    "сохранённые после выхода URL-профили; "
                    "реальные POST-запросы к своим SMS API; необязательная проверка "
                    "доставки через message_id; история HTTP-статусов.", color=WHITE
                ),
                ft.Text(
                    "Telegram OAuth и другие страницы авторизации открываются в браузере. "
                    "Приложение не генерирует массовые запросы кодов входа.", color=WARN,
                ),
                ft.Text(
                    "API-ключ хранится только в текущем поле ввода. URL-профили "
                    "хранятся в настройках устройства — не вставляйте секреты в URL. "
                    "Подтверждение доставки зависит от формата API провайдера.", color=MUTED,
                ),
            ),
        ]
        page.update()

    header = ft.Container(
        padding=12,
        border_radius=16,
        bgcolor=SURFACE,
        content=ft.Column([
            ft.Text("SMS TEST", color=BLUE, size=28, weight=ft.FontWeight.BOLD),
            ft.Text("v3.1  •  Android  •  Автор: @zronu", color=MUTED, size=12),
        ], spacing=2),
    )
    tabs = ft.Row([
        ft.OutlinedButton("Главная", on_click=render_home),
        ft.OutlinedButton("+ Ссылки", on_click=render_links),
        ft.OutlinedButton("История", on_click=render_history),
        ft.OutlinedButton("Инфо", on_click=render_about),
    ], wrap=True, spacing=5)

    page.add(ft.SafeArea(
        expand=True,
        content=ft.Column(
            controls=[header, tabs, feedback, main_column],
            expand=True,
            spacing=10,
        ),
    ))
    render_home()
    if storage_warning:
        inform(storage_warning, BAD)


if __name__ == "__main__":
    ft.run(main)
