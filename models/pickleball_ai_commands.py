from datetime import date, datetime

from odoo import models

# Shorter patience than the interactive wizards: a stuck scraper call blocks the
# whole chat turn the member is waiting on.
_SCRAPER_TOOL_TIMEOUT = 60

# How many courts /court lists when a name is ambiguous.
_COURT_SUGGEST_LIMIT = 10

# Member-facing Alobo bot commands, layered onto the base catalog.
_ALOBO_COMMAND_HELP = (
    ('findcourt', "/findcourt <tỉnh>, [phường], <19-21>, [ngày] — Tìm sân trống"),
    ('court', "/court <tên sân> — Thông tin sân"),
    ('courtplan', "/courtplan <tên sân> [ngày] — Lịch đặt sân"),
    ('getbooking', "/getbooking — Tạo buổi chơi từ lịch đặt sân Alobo của bạn"),
)


class PickleballAiCommandsAlobo(models.AbstractModel):
    """Alobo-backed slash commands added to pickleball.ai.commands when the
    alobo_connector module is installed: /findcourt, /court, /courtplan,
    /getbooking."""
    _inherit = 'pickleball.ai.commands'

    def _user_command_help(self) -> list:
        return super()._user_command_help() + list(_ALOBO_COMMAND_HELP)

    def _cmd_getbooking(self, args, member):
        """Import the team Alobo account's bookings as draft sessions. The
        sender becomes the booker, so they must be linked to a member."""
        if not member:
            return (
                "Lệnh này cần bạn được liên kết tài khoản trước (bạn sẽ là người đặt sân) — "
                "nhắn tin riêng cho bot rồi nhờ admin liên kết Chat ID vào hồ sơ thành viên."
            )
        account = self.env['alobo.account'].sudo().search([], limit=1)
        if not account:
            return ("Chưa cấu hình tài khoản Alobo. Nhờ admin tạo một 'Alobo Account' "
                    "và đăng nhập một lần để lưu phiên.")

        bookings = account.get_my_bookings(timeout=_SCRAPER_TOOL_TIMEOUT)
        if bookings is None:
            return ("Không đọc được lịch đặt (phiên Alobo hết hạn hoặc lỗi). "
                    "Nhờ admin đăng nhập lại tài khoản Alobo.")

        result = self.env['pickleball.session'].create_nearest_alobo_booking(bookings, member)
        session = result['session']
        if not session:
            return ("Không có lịch đặt sắp tới nào trên Alobo. "
                    "(Lịch đã qua không được tạo; sân chưa đồng bộ cũng bị bỏ qua.)")

        to_hm = self.env['pickleball.ai.tools']._float_to_hm
        head = ("✅ Đã tạo buổi chơi (nháp) từ lịch đặt Alobo:"
                if result['created']
                else f"ℹ️ Buổi chơi này đã có rồi (#{session.id}), không tạo thêm:")
        lines = [
            head,
            f"📅 {session.date.strftime('%d/%m/%Y')} "
            f"{to_hm(session.time_start)}-{to_hm(session.time_end)}",
            f"🏟 {session.court_id.name}"
            + (f" ({session.court_count} sân)" if session.court_count > 1 else ""),
        ]
        if session.court_fee:
            lines.append(f"💰 Tiền sân: {session.court_fee:,.0f} VND")
        return "\n".join(lines)

    def _cmd_findcourt(self, args, member):
        usage = (
            "Cú pháp: /findcourt <tỉnh/thành>, [phường], <giờ từ-giờ đến>, [ngày]\n"
            "vd: /findcourt Hà Nội, Tây Hồ, 19:00-21:00, 05/10\n"
            "vd: /findcourt Hà Nội, 19:00-21:00 (ngày mặc định hôm nay)"
        )
        parts = [p.strip() for p in args.split(',') if p.strip()]
        today = self._today_local()
        day = today
        # Optional trailing date part (dd/mm, dd/mm/yyyy, yyyy-mm-dd).
        if parts and not self._parse_time_range(parts[-1]):
            if not re.search(r'\d[/-]\d', parts[-1]):
                return usage
            day = self._parse_plan_date(parts[-1])
            if not day:
                return f"Ngày không hợp lệ: '{parts[-1]}' (dùng dd/mm hoặc dd/mm/yyyy)."
            if day < today:
                return f"Ngày {day.strftime('%d/%m/%Y')} đã qua, hãy chọn hôm nay hoặc ngày sau."
            parts = parts[:-1]
        if len(parts) not in (2, 3):
            return usage
        time_range = self._parse_time_range(parts[-1])
        if not time_range:
            return f"Khung giờ không hợp lệ: '{parts[-1]}'.\n{usage}"
        province_name = parts[0]
        ward_name = parts[1] if len(parts) == 3 else None

        province = self.env['res.country.state'].sudo().search([
            ('country_id.code', '=', 'VN'), ('name', 'ilike', province_name),
        ], limit=1)
        if not province:
            return f"Không tìm thấy tỉnh/thành nào tên '{province_name}'."
        if not province.external_code:
            return f"Tỉnh/thành '{province.name}' chưa được cấu hình mã tra cứu sân."

        ward = self.env['res.country.ward']
        if ward_name:
            ward = ward.sudo().search([
                ('state_id', '=', province.id), ('name', 'ilike', ward_name),
            ], limit=1)
            if not ward:
                return f"Không tìm thấy phường/xã '{ward_name}' thuộc {province.name}."

        (h1, m1), (h2, m2) = time_range
        branches = self.env['alobo.client'].search_available_branches(
            province_code=province.external_code,
            date_start=self._local_to_utc_naive(day, h1, m1),
            date_end=self._local_to_utc_naive(day, h2, m2),
            ward_code=ward.code if ward else None,
            timeout=_SCRAPER_TOOL_TIMEOUT,
        )
        if branches is None:
            return "Tra cứu sân thất bại (lỗi hoặc quá thời gian). Thử lại sau nhé."

        area = f"{ward.name}, {province.name}" if ward else province.name
        window = f"{h1:02d}:{m1:02d}–{h2:02d}:{m2:02d} ngày {day.strftime('%d/%m/%Y')}"
        venues = [b for b in branches if b.get('availableYards')]
        if not venues:
            return f"Không tìm thấy sân trống nào ở {area} ({window})."
        lines = [
            f"- {v.get('name')}: {', '.join(y.get('name', '') for y in v['availableYards'])}"
            f"\n  📍 {v.get('address') or '—'}"
            for v in venues[:15]
        ]
        more = f"\n…và {len(venues) - 15} sân khác." if len(venues) > 15 else ""
        return f"🏓 Sân trống ở {area} ({window}):\n" + "\n".join(lines) + more

    def _cmd_court(self, args, member):
        query = args.strip()
        if not query:
            return "Cú pháp: /court <tên sân>\nvd: /court Đông Đô Grand"

        if query.lstrip('#').isdigit():
            courts = self.env['pickleball.court'].sudo().search(
                [('id', '=', int(query.lstrip('#')))], limit=1,
            )
        else:
            courts = self._find_courts(query)
        if not courts:
            return f"Không tìm thấy sân nào tên '{query}'."
        if len(courts) > 1:
            lines = [
                f"- #{c.id} {c.name}" + (f" ({c.address.splitlines()[0]})" if c.address else "")
                for c in courts[:_COURT_SUGGEST_LIMIT]
            ]
            more = "\n…và còn nữa, ghi rõ tên hơn nhé." if len(courts) > _COURT_SUGGEST_LIMIT else ""
            return (
                f"Có nhiều sân gần đúng với '{query}', bạn muốn xem sân nào?\n"
                + "\n".join(lines) + more
                + "\n\nGõ /court <tên sân chính xác> hoặc /court #<ID>."
            )

        court = courts
        if court.evening_close > court.morning_open:
            hours = (f"{self._minutes_to_hm(court.morning_open * 60)} - "
                     f"{self._minutes_to_hm(court.evening_close * 60)}")
        else:
            hours = "Chưa có thông tin"
        return (
            f"🏟 Tên sân: {court.name}\n"
            f"📍 Địa chỉ: {court.address or 'Chưa có thông tin'}\n"
            f"🕒 Thời gian mở: {hours}"
        )

    def _cmd_courtplan(self, args, member):
        usage = "Cú pháp: /courtplan <tên sân> [ngày]\nvd: /courtplan Sport D Ball 05/10"
        tokens = args.split()
        if not tokens:
            return usage
        day = self._parse_plan_date(tokens[-1])
        if day:
            tokens = tokens[:-1]
        elif re.search(r'\d[/-]\d', tokens[-1]):
            return f"Ngày không hợp lệ: '{tokens[-1]}' (dùng dd/mm hoặc dd/mm/yyyy)."
        else:
            day = self._today_local()
        court_name = ' '.join(tokens)
        if not court_name:
            return usage

        courts = self.env['pickleball.court'].sudo().search([
            ('name', 'ilike', court_name), ('alobo_branch_id', '!=', False),
        ], limit=10)
        if not courts:
            return f"Không tìm thấy sân nào tên '{court_name}' (chỉ tra được các sân đã đồng bộ từ Alobo)."
        exact = courts.filtered(lambda c: c.name.strip().lower() == court_name.lower())
        if len(exact) == 1 or len(courts) == 1:
            court = exact or courts
        else:
            lines = [f"- {c.name}" for c in courts]
            return f"Có nhiều sân khớp '{court_name}', ghi rõ tên hơn:\n" + "\n".join(lines)

        slots = self.env['pickleball.court']._get_booking_schedule(court, day, timeout=_SCRAPER_TOOL_TIMEOUT)
        if slots is None:
            return "Tra cứu lịch sân thất bại (lỗi hoặc quá thời gian). Thử lại sau nhé."
        return self._format_court_plan(court, day, slots)

    def _format_court_plan(self, court, day, slots) -> str:
        has_hours = court.evening_close > court.morning_open
        open_min, close_min = court.morning_open * 60, court.evening_close * 60
        header = f"📋 Lịch sân {court.name} — {day.strftime('%d/%m/%Y')}"
        if has_hours:
            header += f"\n🕒 Giờ mở cửa: {self._minutes_to_hm(open_min)}–{self._minutes_to_hm(close_min)}"

        if not slots:
            return f"{header}\n✅ Chưa có lượt đặt nào — tất cả các sân đều trống."

        # Alobo only reports bookings, so free time = opening hours minus the
        # merged booked intervals of each yard.
        booked_by_yard = {}
        for slot in slots:
            start = self._hm_to_minutes(slot.get('time_start'))
            end = self._hm_to_minutes(slot.get('time_end'))
            if start is None or end is None or end <= start:
                continue
            booked_by_yard.setdefault(slot.get('yard_name') or '?', []).append((start, end))

        def yard_sort_key(name):
            digits = re.findall(r'\d+', name)
            return (int(digits[-1]) if digits else 0, name)

        blocks = []
        for yard in sorted(booked_by_yard, key=yard_sort_key):
            merged = []
            for start, end in sorted(booked_by_yard[yard]):
                if merged and start <= merged[-1][1]:
                    merged[-1][1] = max(merged[-1][1], end)
                else:
                    merged.append([start, end])

            rows = []
            cursor = open_min
            for start, end in merged:
                if has_hours and start > cursor:
                    rows.append((cursor, start, "✅ Trống"))
                rows.append((start, end, "❌ Đã đặt"))
                cursor = max(cursor, end)
            if has_hours and cursor < close_min:
                rows.append((cursor, close_min, "✅ Trống"))

            lines = [
                f"  {self._minutes_to_hm(s)}–{self._minutes_to_hm(e)} {label}"
                for s, e, label in rows
            ]
            blocks.append(f"{yard}:\n" + "\n".join(lines))

        footer = "\n\n(Sân không có trong danh sách: trống cả ngày.)"
        return f"{header}\n\n" + "\n\n".join(blocks) + footer

    # ── Manager commands (write financial/session data) ────────────────────────
