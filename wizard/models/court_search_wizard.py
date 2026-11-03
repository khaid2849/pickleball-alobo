import logging

from odoo import api, fields, models, Command, _
from odoo.exceptions import UserError
from odoo.addons.alobo_connector.models.alobo_client import SPORT_PICKLEBALL

_logger = logging.getLogger(__name__)


class PickleballCourtSearch(models.TransientModel):
    _name = 'pickleball.court.search'
    _description = 'Search for Available Courts'

    def _get_default_province(self):
        return self.env.ref('base.state_vn_VN-HN')

    province_id = fields.Many2one(
        comodel_name='res.country.state',
        string='Province / City',
        required=True,
        domain="[('country_id.code', '=', 'VN'), ('active', '=', True)]",
        default=_get_default_province,
    )
    ward_id = fields.Many2one(
        comodel_name='res.country.ward',
        string='Ward / Commune',
        domain="[('state_id', '=', province_id)]",
    )
    date_start = fields.Datetime(
        string='From',
        required=True,
    )
    date_end = fields.Datetime(
        string='To',
        required=True,
    )
    # Hidden — defaults to Pickleball. Exposed for future multi-sport expansion.
    sport_type = fields.Integer(
        string='Sport Type',
        default=SPORT_PICKLEBALL,
    )
    state = fields.Selection(
        selection=[('search', 'Search'), ('done', 'Done')],
        default='search',
        required=True,
    )
    total_count = fields.Integer(string='Total Venues', default=0, readonly=True)
    available_count = fields.Integer(string='With Available Courts', default=0, readonly=True)
    result_ids = fields.One2many(
        comodel_name='pickleball.court.search.result',
        inverse_name='search_id',
        string='Results',
        readonly=True,
    )

    @api.onchange('province_id')
    def _onchange_province_id(self) -> None:
        self.ward_id = False

    def action_search(self) -> dict:
        self.ensure_one()
        if not self.province_id.external_code:
            raise UserError(_(
                "Province '%s' has no external code configured. "
                "Please verify the tangerine_address_base module data is installed."
            ) % self.province_id.name)

        province_code = self.province_id.external_code
        ward_code = self.ward_id.code if self.ward_id else None

        branches = self.env['alobo.client'].search_available_branches(
            province_code=province_code,
            date_start=self.date_start,
            date_end=self.date_end,
            sport_types=[self.sport_type],
            ward_code=ward_code,
        )
        if branches is None:
            raise UserError(_(
                "Search failed. Check server logs, or verify Playwright is installed:\n"
                "  pip install playwright\n  playwright install chromium"
            ))

        result_commands = [Command.clear()]
        for branch in branches:
            yards = branch.get('availableYards', [])
            result_commands.append(Command.create({
                'branch_name': branch.get('name', ''),
                'address': branch.get('address', ''),
                'phone': branch.get('phone', ''),
                'rating': branch.get('rating', ''),
                'available_yards': ', '.join(y['name'] for y in yards),
                'yard_count': len(yards),
                'has_availability': bool(yards),
            }))

        available_count = sum(
            1 for b in branches if b.get('availableYards')
        )
        self.write({
            'result_ids': result_commands,
            'state': 'done',
            'total_count': len(branches),
            'available_count': available_count,
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'pickleball.court.search',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': self.env.context,
        }

    def action_new_search(self) -> dict:
        """Open a fresh search form instead of resetting in place."""
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'pickleball.court.search',
            'view_mode': 'form',
            'target': 'new',
        }


class PickleballCourtSearchResult(models.TransientModel):
    _name = 'pickleball.court.search.result'
    _description = 'Court Search Result'
    _order = 'has_availability desc, branch_name asc'

    search_id = fields.Many2one(
        comodel_name='pickleball.court.search',
        string='Search',
        required=True,
        ondelete='cascade',
        index=True,
    )
    branch_name = fields.Char(string='Venue', readonly=True)
    address = fields.Char(string='Address', readonly=True)
    phone = fields.Char(string='Phone', readonly=True)
    rating = fields.Char(string='Rating', readonly=True)
    available_yards = fields.Char(string='Available Courts', readonly=True)
    yard_count = fields.Integer(string='#', readonly=True)
    has_availability = fields.Boolean(string='Available', readonly=True)
