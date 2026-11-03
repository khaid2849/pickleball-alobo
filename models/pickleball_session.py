from datetime import datetime, timedelta

from odoo import api, fields, models, _

# Alobo booking.status → whether it becomes a session.
# 0 = pending/new, 1 = confirmed, 5 = completed; -2 = cancelled (skipped).
_SESSIONABLE_STATUS = {0, 1, 5}


class PickleballSession(models.Model):
    """Adds the Alobo court-search button and booking-import to sessions when
    alobo_connector is installed."""
    _inherit = 'pickleball.session'

    alobo_booking_id = fields.Char(
        string='Alobo Booking ID', index=True, copy=False, readonly=True,
        help='Unique booking id from Alobo — dedup key for /getbooking so the '
             'same booking is never imported twice.',
    )

    def action_open_court_search(self) -> dict:
        """Open the Alobo court-search wizard as a popup dialog."""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Search Available Courts'),
            'res_model': 'pickleball.court.search',
            'view_mode': 'form',
            'target': 'new',
            'context': {'form_view_initial_mode': 'edit'},
        }

    # ── Alobo bookings → draft sessions ─────────────────────────────────────
    @staticmethod
    def _unwrap(node):
        """Alobo wraps each record as {"a": <data>, "b": ..., "c": ...}."""
        if isinstance(node, dict) and isinstance(node.get('a'), dict):
            return node['a']
        return node if isinstance(node, dict) else {}

    @api.model
    def _parse_alobo_booking(self, raw: dict) -> dict | None:
        """One raw Alobo booking → pickleball.session values (court_id, date,
        time_start/end, court_count, court_fee, alobo_booking_id), or None when
        it can't be used (cancelled, no services, or no matching synced court).
        See [[alobo-list-bookings-shape]] for the source JSON shape."""
        booking = self._unwrap(raw)
        bid = booking.get('id')
        if not bid or booking.get('status') not in _SESSIONABLE_STATUS:
            return None

        services = [self._unwrap(s) for s in booking.get('services', [])]
        starts = []
        ends = []
        courts = set()
        for svc in services:
            raw_start = (svc.get('startTime') or '').replace('.000', '')
            try:
                dt = datetime.fromisoformat(raw_start)
            except (ValueError, TypeError):
                continue
            starts.append(dt)
            ends.append(dt + timedelta(minutes=int(svc.get('duration') or 0)))
            if svc.get('serviceId'):
                courts.add(svc['serviceId'])
        if not starts:
            return None

        court = self.env['pickleball.court'].sudo().search(
            [('alobo_branch_id', '=', booking.get('branchId'))], limit=1)
        if not court:
            return None

        dt_start, dt_end = min(starts), max(ends)
        return {
            'alobo_booking_id': bid,
            'court_id': court.id,
            'date': dt_start.date(),
            'time_start': dt_start.hour + dt_start.minute / 60.0,
            'time_end': dt_end.hour + dt_end.minute / 60.0,
            'court_count': max(len(courts), 1),
            'court_fee': float(booking.get('totalPrice') or 0),
            '_booking_code': booking.get('bookingCode'),
        }

    @api.model
    def create_nearest_alobo_booking(self, bookings: list, booker) -> dict:
        """Create a draft session for the NEAREST UPCOMING booking only.

        Past bookings are ignored; among the future ones the earliest is picked.
        If it was already imported (by alobo_booking_id) nothing is created.
        Returns {session, created, upcoming_total}: `session` is the new or
        existing record (empty when there is no upcoming booking), `created` is
        False when it already existed, `upcoming_total` counts the future
        bookings found."""
        today = fields.Date.context_today(self)
        candidates = []
        for raw in (bookings or []):
            vals = self._parse_alobo_booking(raw)
            if vals and vals['date'] >= today:
                candidates.append(vals)
        if not candidates:
            return {'session': self.browse(), 'created': False, 'upcoming_total': 0}

        candidates.sort(key=lambda v: (v['date'], v['time_start']))
        vals = candidates[0]
        existing = self.sudo().search(
            [('alobo_booking_id', '=', vals['alobo_booking_id'])], limit=1)
        if existing:
            return {'session': existing, 'created': False, 'upcoming_total': len(candidates)}

        code = vals.pop('_booking_code', None)
        note = _("[Imported from Alobo booking #%s — review before confirming]",
                 code or vals['alobo_booking_id'])
        session = self.create({
            **vals,
            'booker_id': booker.id if booker else False,
            'participant_ids': [(6, 0, booker.ids)] if booker else False,
            'notes': note,
            'state': 'draft',
        })
        return {'session': session, 'created': True, 'upcoming_total': len(candidates)}
