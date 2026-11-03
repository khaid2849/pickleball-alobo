import logging

from odoo import api, fields, models, _

from odoo.addons.alobo_connector.models.alobo_client import SPORT_PICKLEBALL

_logger = logging.getLogger(__name__)


class PickleballCourt(models.Model):
    """Adds the Alobo-synced data + live-lookup helpers to pickleball.court.
    Present only when alobo_connector is installed; pickleball-team's own court
    model carries just the manual fields."""
    _inherit = 'pickleball.court'

    # ── Alobo sync fields ────────────────────────────────────────────────────
    alobo_branch_id = fields.Char(
        string='Alobo Branch ID', index=True, copy=False, readonly=True,
        help='Unique branch slug from Alobo (e.g. sport_d_ball_pickleball).',
    )
    total_star = fields.Float(
        string='Total Stars', readonly=True, digits=(10, 1),
        help='Sum of all star ratings from Alobo (divide by total_rating for average).',
    )
    total_rating = fields.Integer(
        string='Rating Count', readonly=True,
        help='Number of ratings received on Alobo.',
    )
    latitude = fields.Float(string='Latitude', digits=(10, 7))
    longitude = fields.Float(string='Longitude', digits=(10, 7))
    province_code = fields.Char(string='Province Code')
    ward_code = fields.Char(string='Ward Code')
    morning_open = fields.Integer(
        string='Opens at (hour)',
        help='Hour of day the court opens (morningStartWorkingTime from Alobo).',
    )
    evening_close = fields.Integer(
        string='Closes at (hour)',
        help='Hour of day the court closes (afternoonEndWorkingTime from Alobo).',
    )
    last_alobo_sync = fields.Datetime(string='Last Alobo Sync', readonly=True, copy=False)

    # ── Alobo sync ───────────────────────────────────────────────────────────
    @api.model
    def action_sync_alobo_courts(self) -> bool:
        """Upsert all Pickleball courts from the Alobo platform into this model,
        keyed on alobo_branch_id. Courts not present in Alobo are left untouched;
        a court whose Alobo status != 1 is marked active=False; manually-created
        courts (no alobo_branch_id) are never modified.

        Called by the daily cron and runnable manually from the UI."""
        _logger.info("Alobo court sync: starting")

        branches = self.env['alobo.client'].fetch_all_branches(sport_type=SPORT_PICKLEBALL)
        if not branches:
            _logger.warning("Alobo court sync: scraper returned no branches — aborting")
            return False

        # sudo() needed because the cron user (OdooBot) may not have write access
        # under the base group; the sync is a trusted scheduled operation.
        Court = self.sudo()

        # Province: external_code (e.g. "01") → res.country.state id
        province_map = {
            s.external_code: s.id
            for s in self.env['res.country.state'].sudo().search([
                ('country_id.code', '=', 'VN'),
                ('external_code', '!=', False),
                ('active', '=', True),
            ])
        }
        # Ward: (province_external_code, ward_code) → res.country.ward id.
        ward_map = {}
        for w in self.env['res.country.ward'].sudo().search([
            ('state_id.country_id.code', '=', 'VN'),
            ('code', '!=', False),
            ('active', '=', True),
        ]):
            ward_map[(w.state_id.external_code or '', w.code)] = w.id

        # active_test=False is essential: an Alobo branch with status != 1 is
        # stored active=False, and a default search hides inactive records — so
        # without this the lookup misses every inactive court and re-creates it
        # as a duplicate on every run (historically ~500 dup rows/day).
        existing = {
            c.alobo_branch_id: c
            for c in Court.with_context(active_test=False).search(
                [('alobo_branch_id', '!=', False)])
        }

        now = fields.Datetime.now()
        to_create = []
        updated = 0

        for branch in branches:
            bid = branch.get('id', '').strip()
            if not bid:
                continue

            pcode = (branch.get('provinceCode') or '')[-2:]
            wcode = (branch.get('wardCode') or '')[-5:]
            loc = branch.get('location') or {}
            vals = {
                'name': branch.get('name') or _('Unnamed Court'),
                'address': branch.get('address') or False,
                'phone': branch.get('phone') or False,
                'phone2': branch.get('phone2') or False,
                'total_star': float(branch.get('totalStar') or 0),
                'total_rating': int(branch.get('totalRating') or 0),
                'latitude': float(loc.get('latitude') or 0.0),
                'longitude': float(loc.get('longitude') or 0.0),
                'province_code': pcode or False,
                'ward_code': wcode or False,
                'province_id': province_map.get(pcode, False),
                'ward_id': ward_map.get((pcode, wcode), False),
                'morning_open': int(branch.get('morningStartWorkingTime') or 0),
                'evening_close': int(branch.get('afternoonEndWorkingTime') or 0),
                'active': branch.get('status') == 1,
                'last_alobo_sync': now,
            }

            if bid in existing:
                existing[bid].write(vals)
                updated += 1
            else:
                vals['alobo_branch_id'] = bid
                to_create.append(vals)

        if to_create:
            Court.create(to_create)

        _logger.info(
            "Alobo court sync: created=%d updated=%d total_from_api=%d",
            len(to_create), updated, len(branches),
        )
        return True

    @api.model
    def _get_booking_schedule(self, court, date, timeout: int = 180) -> list | None:
        """A synced court's booked slots for one day from Alobo. None on
        failure/timeout, [] if the court genuinely has no bookings that day.
        Used by the court-schedule wizard and the AI get_court_schedule tool."""
        return self.env['alobo.client'].get_booking_schedule(
            court.alobo_branch_id, date, timeout=timeout,
        )
